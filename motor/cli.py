"""CLI do motor de dados — `python -m motor <comando>`.

Comandos:
  ingest <termos...>   pagina a API e grava as peças no SQLite
  show <numero>        mostra uma peça do banco (cross-ref, dimensões, veículos)
  stats                resumo do banco
"""

import argparse
from collections import Counter

from .ingest import ingest_terms, sweep_catalogs, KNOWN_CATALOGS
from .session import DEFAULT_CATALOG, FragaSession
from .http_session import HttpFragaSession
from .store import Store


def _session_cls(args):
    """Escolhe a sessão: --http (urllib, leve) ou padrão (Playwright)."""
    return HttpFragaSession if getattr(args, "http", False) else FragaSession


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
    pi.set_defaults(func=_cmd_ingest)

    pw = sub.add_parser("sweep", help="varre o catálogo INTEIRO (query vazia)")
    pw.add_argument("--catalog", action="append",
                    help="URL de catálogo Fraga (repetível; padrão: catálogos conhecidos)")
    pw.add_argument("--max", type=int, default=None, help="teto de peças por catálogo")
    pw.add_argument("--page-size", type=int, default=50, help="itens por página (máx 50)")
    pw.add_argument("--headed", action="store_true", help="mostra o navegador")
    pw.add_argument("--http", action="store_true",
                    help="usa sessão HTTP leve (urllib, sem Chromium)")
    pw.set_defaults(func=_cmd_sweep)

    ps = sub.add_parser("show", help="mostra uma peça do banco")
    ps.add_argument("part_number")
    ps.set_defaults(func=_cmd_show)

    pt = sub.add_parser("stats", help="resumo do banco")
    pt.set_defaults(func=_cmd_stats)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
