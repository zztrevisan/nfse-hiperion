# Levantamento para habilitar a integração ADN

Atualizado em 31/08/2026 com as respostas do responsável. Itens marcados como **pendentes** não devem ser implementados por suposição.

## 1. Pastas dos clientes — confirmado

- Raiz fiscal do ano: `H:\2026`.
- Padrão: `NUMERO BOX - NOME DA EMPRESA`, por exemplo `023 - YU SHEN MINIMERCADO`.
- Estrutura existente:

```text
H:\2026\023 - EMPRESA\02. FISCAL\ARQUIVOS\SERVIÇOS
├── PRESTADOS\PORTAL NACIONAL\MM.AAAA
└── TOMADOS\PORTAL NACIONAL\MM.AAAA
```

- O trabalho é mensal e começa pela competência selecionada. O nome da pasta é `MM.AAAA`, por exemplo `07.2026`.
- Depois de localizar a empresa na raiz fiscal, o aplicativo pode criar as subpastas fiscais ausentes.
- Emitidas/saídas vão para `PRESTADOS`; recebidas/entradas vão para `TOMADOS`.
- Sem documentos: não criar pasta mensal vazia; destacar a empresa para conferência manual.

### Duplicidades — confirmado

- Nunca substituir silenciosamente.
- Sempre apontar a duplicidade ao funcionário.
- Exibir confirmação para baixar mesmo assim ou não.
- Se confirmado, preservar o anterior e salvar o novo com outro nome.
- **Pendente:** a confirmação será por arquivo, por empresa ou uma regra para todo o lote? Uma janela por arquivo pode gerar centenas de confirmações.

## 2. Certificados A1 — parcialmente confirmado

- Formatos `.pfx`/`.p12`, contendo cadeia e chave privada.
- Normalmente cada empresa possui seu próprio certificado.
- Caso um A1 represente mais de uma inscrição, separar pelos CNPJs cadastrados.
- Matriz e filial são inscrições distintas quando têm CNPJs diferentes.
- CNPJ é a chave principal do cadastro e mapeamento fiscal.
- Senha somente na tela, protegida pelo DPAPI do Windows.
- **Pendente:** confirmar por empresa CNPJ, razão social, arquivo A1 e validade.
- **Pendente:** validar se o CNPJ solicitado está autorizado pelo certificado.

## 3. Extensão atual — inspecionada

- Nome: **Baixar NFSe Nota Fiscal de Serviço Eletrônica Emitidas e Recebidas**.
- ID Chrome: `enehmclajcndmgefbmjhecccoegbdgea`.
- Versão inspecionada: `3.0.0.14` (25/08/2026).
- Desenvolvedor informado na loja: CECHINEL / `arcechinel.com.br`.
- Manifest V3; permissões de host limitadas a `https://www.nfse.gov.br/*` e `https://adn.nfse.gov.br/*`.
- A extensão declara ser privada/independente, sem vínculo oficial.
- O modo sem CAPTCHA usa a API oficial ADN por certificado digital/mTLS; não resolve nem contorna CAPTCHA.
- Rota observada: `GET https://adn.nfse.gov.br/contribuintes/DFe/{NSU}?lote=true`.
- Filial/outro CNPJ autorizado: parâmetro opcional `cnpjConsulta={CNPJ}`.
- Cabeçalho: `Accept: application/json`; cache deve ser desativado.
- Paginação: a resposta traz documentos com NSU estritamente maior que o informado. Continuar solicitando a partir do maior NSU recebido, sem somar 1.
- Fim normal: HTTP 404, `StatusProcessamento=NENHUM_DOCUMENTO_LOCALIZADO` ou `LoteDFe` vazio.
- Resposta útil: `LoteDFe[]` com `NSU`, `TipoDocumento`, `ChaveAcesso` e `ArquivoXml`.
- `ArquivoXml`: Base64, normalmente GZIP; após decodificar resulta no XML.
- Classificação: prestador igual ao CNPJ consultado = Emitida; tomador igual = Recebida; `TipoDocumento=EVENTO` = Evento.
- Competência: campo XML `dCompet`, com fallback para emissão apenas quando `dCompet` não existe.
- Eventos usam `chNFSe`, `xDesc`, `xMotivo` e datas do evento.
- Repetição: até 5 tentativas para 429/502/503/504, com espera progressiva. A extensão usa intervalo adaptativo de 500–5000 ms.
- Controle incremental: último NSU por CNPJ.
- DANFSe/PDF é gerado localmente a partir do XML; não é baixado pela rota ADN.
- A extensão suporta matriz→filial pelo `cnpjConsulta`, desde que o certificado tenha autorização.

### Implicação importante da ADN

A rota observada não recebe mês/data. Ela distribui documentos incrementalmente por NSU. Para garantir uma competência escolhida, o aplicativo precisa sincronizar a caixa por NSU, decodificar os XMLs e filtrar localmente por `dCompet`. Na primeira execução de uma empresa, pode ser necessário começar do NSU 0; depois, o SQLite deve guardar o último NSU por CNPJ.

**Pendente antes do primeiro teste real:** validar a chamada com um certificado A1 de teste/autorizado e confirmar o comportamento oficial do mTLS fora do Chrome.

Não enviar cookies, tokens, senhas, chave privada ou conteúdo fiscal real. O código da extensão só será inspecionado com autorização/licença.

## 4. Regras fiscais e operacionais — parcialmente confirmado

- A maioria das empresas é de São Paulo.
- **Pendente:** não inferir município apenas pelo CNPJ; definir fonte oficial e confirmar se ele muda a rota.
- Emitidas e recebidas provavelmente usam consultas distintas; confirmar na extensão.
- Filtro pretendido: competência fiscal `MM/AAAA`.
- **Pendente:** confirmar se a API filtra pelo campo de competência ou pela data de emissão.
- Baixar XML e DANFSe/PDF quando disponíveis.
- Incluir cancelamentos, substituições e manifestações, separados em `MM.AAAA\Eventos` no lado correspondente à nota original.
- Logs sem conteúdo de nota, senha, token ou chave privada.

## 5. Critério de aceite — proposto

Validar primeiro com duas empresas e uma competência pequena:

- contagem confere com extensão e portal;
- CNPJ e direção conferem com `PRESTADOS`/`TOMADOS`;
- XML íntegro e DANFSe/PDF correspondente;
- competência e pastas corretas;
- canceladas/substituídas separadas;
- duplicidade detectada, nunca sobrescrita silenciosamente e renomeada após confirmação;
- zero documentos aparece como `Sem notas`;
- repetição da competência é segura;
- falha em uma empresa não interrompe as demais.

## Próximo insumo necessário

Autorizar um teste controlado com um certificado A1 e uma empresa, sem compartilhar a senha por mensagem. A senha deve ser informada somente na tela local. Também é necessário decidir se a primeira sincronização começará do NSU 0 ou de um NSU já conhecido da extensão.
