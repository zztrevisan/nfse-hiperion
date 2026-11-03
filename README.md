# NFS-e em lote — Hiperion

Aplicativo Windows que baixa os XML de NFS-e de **várias empresas usando um único certificado A1**
(o do contador/procurador) pela API oficial de distribuição do ADN (NFS-e Nacional), e organiza tudo
em pastas por empresa e data.

Versão atual: `2.0.0`. Desenvolvido por Guilherme Andrade dos Santos Trevisan para a Hiperion Assessoria Contábil.

## Como funciona

- Conexão mTLS com `https://adn.nfse.gov.br/contribuintes/DFe/{NSU}?lote=true&cnpjConsulta={CNPJ}`.
- O parâmetro `cnpjConsulta` (ou `cpfConsulta`) faz o certificado conectado consultar outra inscrição.
  O ADN só responde se a empresa tiver dado **procuração eletrônica no e-CAC** ao titular do certificado
  (ou se for filial do CNPJ do certificado). Sem procuração, a empresa aparece em amarelo e o lote continua.
- O download é **incremental**: o último NSU de cada empresa fica salvo, e a próxima execução só traz o que
  é novo. A opção "Baixar tudo de novo" recomeça do NSU 0.
- O NSU só é salvo depois que os arquivos do lote foram gravados — se cair no meio, nada se perde.

## Uso

1. Escolha o certificado A1 (`.pfx`/`.p12`) do procurador e digite a senha (pode ser lembrada; fica protegida pelo DPAPI do Windows).
2. Escolha a pasta de destino.
3. Digite os CNPJ (um por linha) ou clique em **Importar TXT**. Aceita CNPJ numérico, alfanumérico e CPF,
   com ou sem pontuação, e linhas com nome junto. Os inválidos (dígito verificador) são apontados e ignorados.
4. Opcional: marque **Só a competência** e escolha o período (de/até, padrão mês anterior). A caixa é lida
   inteira e só as notas desse período são salvas; o último NSU salvo não muda, então o modo incremental continua certo.
5. Clique em **Baixar XMLs**. Dois cliques numa empresa abrem a pasta dela.

## Estrutura das pastas

```
<pasta escolhida>\
  RAZAO SOCIAL - 11222333000181\
    2026\
      08\
        Emitidas\   10_CLIENTE TESTE_1.xml        (número_contraparte_NSU)
        Recebidas\
        Eventos\    10_Cancelamento de NFS-e_3.xml
        Outros\     (notas em que a empresa não é prestador nem tomador, ex.: intermediário)
```

A data é a **competência** da nota (`dCompet`; se faltar, a emissão). O evento (cancelamento,
substituição etc.) vai para o mês da nota a que se refere.

## Arquivos do projeto

| Arquivo | Função |
|---|---|
| `app/main.py` | Interface (tkinter) |
| `app/adn.py` | Cliente da API ADN e leitura dos XML |
| `app/certificate.py` | Abre o A1 e monta o contexto mTLS |
| `app/sync.py` | Baixa a caixa de cada empresa e grava nas pastas |
| `app/store.py` | SQLite em `%LOCALAPPDATA%\NFSeHiperion` (configurações, NSU por empresa, índice de notas) |
| `app/documents.py` | Leitura da lista e validação de CNPJ/CPF |
| `app/security.py` | DPAPI para a senha |

## Rodar e empacotar

- Rodar: `executar.bat`
- Testes: `.venv\Scripts\python -m unittest discover -s tests -v`
- Gerar `.exe`: `powershell -ExecutionPolicy Bypass -File build.ps1` → `release\NFSe-Hiperion-2.0.0.exe`
