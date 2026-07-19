"""CLI do motor de dados — `python -m motor <comando>`.

Comandos:
  ingest <termos...>   pagina a API e grava as peças no SQLite
  show <numero>        mostra uma peça do banco (cross-ref, dimensões, veículos)
  stats                resumo do banco
"""

import argparse
import functools
import os
import sys
from collections import Counter

from .ingest import ingest_terms, sweep_catalogs, KNOWN_CATALOGS
from .session import DEFAULT_CATALOG, FragaSession
from .http_session import HttpFragaSession
from .auth_session import AuthFragaSession
from .pdf_catalog import ingest_pdf, PARSERS
from .cross_catalog import ingest_cross, PARSERS as CROSS_PARSERS
from .manuals_index import build_index, DEFAULT_ROOT, DEFAULT_DB
from . import amayama
from .store import Store


def _session_cls(args):
    """Escolhe a sessão:
      --login  -> AuthFragaSession (catálogos que fecharam a API e pedem login)
      --http   -> HttpFragaSession (urllib, leve)
      padrão   -> FragaSession (Playwright)
    Credenciais do --login vêm de --user/--pass ou das env FRAGA_USER/FRAGA_PASS.
    """
    if getattr(args, "login", False):
        user = args.user or os.getenv("FRAGA_USER")
        pw = args.password or os.getenv("FRAGA_PASS")
        if not (user and pw):
            sys.exit("erro: --login exige credenciais (use --user/--pass ou "
                     "as variáveis de ambiente FRAGA_USER/FRAGA_PASS)")
        return functools.partial(AuthFragaSession, username=user, password=pw)
    return HttpFragaSession if getattr(args, "http", False) else FragaSession


def _add_login_args(p):
    """Flags de login compartilhados por ingest/sweep (catálogos fechados)."""
    p.add_argument("--login", action="store_true",
                   help="usa sessão autenticada (catálogos que pedem login: cofap, ...)")
    p.add_argument("--user", help="usuário Fraga (ou env FRAGA_USER)")
    p.add_argument("--pass", dest="password", help="senha Fraga (ou env FRAGA_PASS)")


def _cmd_ingest(args):
    res = ingest_terms(
        args.terms,
        db_path=args.db,
        catalog_url=args.catalog,
        max_items=args.max,
        page_size=args.page_size,
        headless=not args.headed,
        session_cls=_session_cls(args),
    )
    total = sum(res.values())
    print(f"\n== ingestão concluída: {total} peças em {len(res)} termo(s) ==")


def _cmd_sweep(args):
    catalogs = args.catalog or KNOWN_CATALOGS
    res = sweep_catalogs(
        catalog_urls=catalogs,
        db_path=args.db,
        max_items=args.max,
        page_size=args.page_size,
        headless=not args.headed,
        session_cls=_session_cls(args),
    )
    print("\n== varredura concluída ==")
    total = 0
    for label, n in res.items():
        print(f"   {label}: {n}")
        if isinstance(n, int):
            total += n
    print(f"   TOTAL: {total} peças em {len(catalogs)} catálogo(s)")


def _cmd_pdf(args):
    label = args.catalog or (args.brand.lower() + " (pdf)")
    n = ingest_pdf(args.pdf, catalog_label=label, brand=args.brand,
                   fmt=args.format, db_path=args.db)
    print(f"\n== PDF ingerido: {n} peças em {label!r} ==")


def _cmd_cross(args):
    label = args.catalog or (args.brand.lower() + " (cross)")
    n = ingest_cross(args.file, catalog_label=label, brand=args.brand,
                     fmt=args.format, db_path=args.db)
    print(f"\n== cross ingerido: {n} peças em {label!r} ==")


def _cmd_amayama(args):
    if args.part:
        mk, _, code = args.part.partition("/")
        codes = [(mk.lower(), code.lower())]
    elif args.html:
        with open(args.html, encoding="utf-8", errors="replace") as f:
            codes = amayama.extract_part_codes(f.read(), make=args.make)
    else:
        sys.exit("erro: informe --html <arquivo do chassi> ou --part <marca/código>")
    if args.limit:
        codes = codes[: args.limit]
    print(f"» {len(codes)} código(s) de peça")
    if args.dump_codes:
        for mk, code in codes:
            print(f"  {mk}/{code}")
        return
    n = amayama.ingest_amayama(codes, catalog_label=args.catalog or "amayama",
                               db_path=args.db, delay=args.delay)
    print(f"\n== Amayama ingerido: {n} peças ==")


def _cmd_manuals(args):
    total = build_index(root=args.root or DEFAULT_ROOT, db_path=args.out or DEFAULT_DB)
    print(f"\n== índice de manuais: {total} arquivos ==")


def _cmd_show(args):
    store = Store(args.db) if args.db else Store()
    try:
        found = store.get_product(args.part_number)
    finally:
        store.close()
    if not found:
        print(f"nada no banco para {args.part_number!r} (já rodou o ingest?)")
        return
    for rec in found:
        p = rec["product"]
        print(f"\n══ Peça {p['part_number']} ({p['brand']}) — grupo: {p['product_group']}")
        if p.get("application"):
            print(f"   aplicação: {p['application'][:100]}")
        xr = rec["cross_references"]
        print(f"   OEM/equivalentes ({len(xr)}):")
        for c in xr[:15]:
            print(f"      {str(c['brand']):22} {c['part_number']}")
        dims = [s for s in rec["specifications"] if s.get("value")]
        if dims:
            print(f"   especificações ({len(dims)}):")
            for s in dims[:10]:
                print(f"      {s['description']}: {s['value']}")
        vs = rec["vehicles"]
        brands = Counter(v["brand"] for v in vs if v.get("brand"))
        print(f"   veículos atendidos: {len(vs)} — marcas: {dict(brands)}")
        for v in vs[:8]:
            print(f"      · {v['brand']} {v.get('name') or ''} {v.get('model') or ''} {v.get('engine_name') or ''}")


def _cmd_stats(args):
    store = Store(args.db) if args.db else Store()
    try:
        s = store.stats()
    finally:
        store.close()
    print("== estatísticas do banco ==")
    print(f"  peças ................ {s['products']}")
    print(f"  cross-references ..... {s['cross_refs']}")
    print(f"  especificações ....... {s['specs']}")
    print(f"  veículos (linhas) .... {s['vehicles']}")
    print(f"  marcas de veículo .... {s['distinct_vehicle_brands']}")
    print("  peças por marca-fonte:")
    for r in s["top_source_brands"]:
        print(f"      {str(r['brand']):22} {r['n']}")
    print("  últimas ingestões:")
    for r in s["ingests"]:
        print(f"      [{r['ts']}] {r['term']!r} @ {r['catalog']} → {r['count']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="motor", description="Motor de dados de peças (Fraga).")
    ap.add_argument("--db", help="caminho do SQLite (padrão: acha_peca.db na raiz)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="busca e grava peças")
    pi.add_argument("terms", nargs="+", help="termos de busca (ex.: 'retentor')")
    pi.add_argument("--catalog", default=DEFAULT_CATALOG, help="URL do catálogo Fraga")
    pi.add_argument("--max", type=int, default=None, help="teto de peças por termo")
    pi.add_argument("--page-size", type=int, default=50, help="itens por página (máx 50)")
    pi.add_argument("--headed", action="store_true", help="mostra o navegador")
    pi.add_argument("--http", action="store_true",
                    help="usa sessão HTTP leve (urllib, sem Chromium)")
    _add_login_args(pi)
    pi.set_defaults(func=_cmd_ingest)

    pw = sub.add_parser("sweep", help="varre o catálogo INTEIRO (query vazia)")
    pw.add_argument("--catalog", action="append",
                    help="URL de catálogo Fraga (repetível; padrão: catálogos conhecidos)")
    pw.add_argument("--max", type=int, default=None, help="teto de peças por catálogo")
    pw.add_argument("--page-size", type=int, default=50, help="itens por página (máx 50)")
    pw.add_argument("--headed", action="store_true", help="mostra o navegador")
    pw.add_argument("--http", action="store_true",
                    help="usa sessão HTTP leve (urllib, sem Chromium)")
    _add_login_args(pw)
    pw.set_defaults(func=_cmd_sweep)

    pp = sub.add_parser("pdf", help="ingere um catálogo em PDF (marcas sem API)")
    pp.add_argument("pdf", help="caminho do PDF")
    pp.add_argument("--brand", default="NAKATA", help="marca fabricante (padrão: NAKATA)")
    pp.add_argument("--catalog", help="rótulo do catálogo (padrão: '<marca> (pdf)')")
    pp.add_argument("--format", choices=sorted(PARSERS), default="nakata-table",
                    help="formato da tabela (padrão: nakata-table)")
    pp.set_defaults(func=_cmd_pdf)

    pc = sub.add_parser("cross", help="ingere tabela de intercâmbio (xls: código↔OEM)")
    pc.add_argument("file", help="caminho da planilha .xls de cross")
    pc.add_argument("--brand", default="555", help="marca fabricante (padrão: 555)")
    pc.add_argument("--catalog", help="rótulo do catálogo (padrão: '<marca> (cross)')")
    pc.add_argument("--format", choices=sorted(CROSS_PARSERS), default="cross-xls",
                    help="formato da planilha (padrão: cross-xls)")
    pc.set_defaults(func=_cmd_cross)

    pa = sub.add_parser("amayama", help="ingere peças genuínas do Amayama (via HTML de chassi)")
    pa.add_argument("--html", help="HTML da página do chassi/diagrama (salvo do navegador)")
    pa.add_argument("--make", help="filtra os códigos por marca (ex.: subaru)")
    pa.add_argument("--part", help="ingere UMA peça: 'marca/código' (ex.: subaru/803924080)")
    pa.add_argument("--dump-codes", action="store_true", help="só lista os códigos extraídos")
    pa.add_argument("--limit", type=int, help="teto de peças")
    pa.add_argument("--delay", type=float, default=2.5, help="segundos entre requests (gentil)")
    pa.add_argument("--catalog", help="rótulo do catálogo (padrão: amayama)")
    pa.set_defaults(func=_cmd_amayama)

    pm = sub.add_parser("manuals", help="indexa os manuais de fábrica espelhados (manuals.db)")
    pm.add_argument("--root", help=f"raiz do mirror (padrão: {DEFAULT_ROOT})")
    pm.add_argument("--out", help="caminho do manuals.db (padrão: manuals.db na raiz)")
    pm.set_defaults(func=_cmd_manuals)

    ps = sub.add_parser("show", help="mostra uma peça do banco")
    ps.add_argument("part_number")
    ps.set_defaults(func=_cmd_show)

    pt = sub.add_parser("stats", help="resumo do banco")
    pt.set_defaults(func=_cmd_stats)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
