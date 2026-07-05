"""Query GraphQL do motor — a peça completa (dado-âncora).

Combina os campos JÁ PROVADOS nas provas (prova2/): a operação real GetProducts
do app trouxe id/crossReferences/specifications/pageInfo; as provas de aplicações
confirmaram vehicles/summaryApplication/oldCodes. Aqui reunimos tudo num único
node, com paginação (skip/take) e pageInfo.total para saber quando parar.

Nota: alguns subcampos de Vehicle são restritos (AUTH_NOT_AUTHORIZED → 401) na
sessão pública do catálogo — release e fuel. Ficamos com o conjunto liberado:
brand, name, model, engineName, engineConfiguration.
"""

# Operação enxuta (sem __typename, sem imagens/links/distribuidores que não
# guardamos) mas com TODOS os pilares do banco: cross-ref OEM, dimensões e
# veículos. pageInfo.total dá o tamanho total do resultado -> paginação.
PRODUCT_QUERY = """query MotorProducts($query:String!,$market:MarketType!,$take:Int,$skip:Int,$onlyWithCodeDistributor:Boolean!){
  catalogSearch(query:$query, market:$market, take:$take, skip:$skip, onlyWithCodeDistributor:$onlyWithCodeDistributor){
    nodes{
      product{
        id
        partNumber
        brand{ name }
        productGroup{ name }
        status
        summaryApplication
        containsUniversalApplication
        oldCodes
        crossReferences{ brand{ name } partNumber }
        specifications{ category important description value }
        vehicles{ brand name model engineName engineConfiguration }
      }
    }
    pageInfo{ total take }
  }
}"""

OPERATION_NAME = "MotorProducts"
