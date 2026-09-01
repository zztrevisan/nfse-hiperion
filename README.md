# NFS-e em lote — MVP local para Windows

Aplicativo local em Python para selecionar uma competência e processar várias empresas sem interromper o lote quando uma delas falha.

Versão atual: `1.2.1`.

Desenvolvido por Guilherme Andrade dos Santos Trevisan para a Hiperion Assessoria Contábil.

## Documentação do projeto

O documento abaixo apresenta o design system, a arquitetura de software, os principais
fluxogramas, a estrutura de pastas, os controles de segurança e o mapa de evolução do produto:

- [Design system, arquitetura e fluxos - versão 1.2.1](output/pdf/NFSe-Hiperion-Design-Arquitetura-Fluxos-v1.2.1.pdf)

## O que já funciona

- cadastro de empresas (CNPJ, razão social e certificado A1 `.pfx`/`.p12`);
- edição do cadastro pelo botão **Editar** ou com dois cliques na empresa;
- importação em lote da planilha de cadastros do SIEG e de uma pasta inteira de certificados;
- leitura automática de `NUMERO BOX - RAZAO SOCIAL\CERTIFICADO DIGITAL\arquivo.pfx`;
- descoberta da pasta `NUMERO BOX - RAZAO SOCIAL`, preferencialmente por um arquivo marcador de CNPJ;
- destino fiscal: emitidas em `02. FISCAL\ARQUIVOS\SERVIÇOS\PRESTADOS\PORTAL NACIONAL\MM.AAAA` e recebidas em `...\TOMADOS\PORTAL NACIONAL\MM.AAAA`;
- fila com progresso, log na tela e relatório final;
- seleção independente entre `Emitidas / Prestados` e `Recebidas / Tomados`;
- execução para todas as empresas ou somente uma empresa escolhida;
- quadro final por empresa: verde para baixada e vermelho para sem notas/erro;
- painel **Ver erros** com detalhes e caminho pesquisado;
- duplo clique em resultado concluído abre Tomados ou Prestados da competência;
- dois cliques em uma empresa vermelha abrem o Portal Nacional para conferência manual;
- banco SQLite local;
- senha do A1 protegida pelo DPAPI do Windows — nunca gravada em texto puro;
- modo de simulação, que valida cadastro/pastas e cria arquivos demonstrativos claramente identificados;
- integração ADN por certificado A1/mTLS, paginação por NSU e filtro local por competência;
- eventos de cancelamento, substituição e manifestação dentro de `MM.AAAA\Eventos`;

## Antes da integração real: dados necessários

Preencha `LEVANTAMENTO_API.md`. Em particular, ainda são necessários:

1. teste controlado do mTLS com um A1 cadastrado localmente;
2. decisão do NSU inicial na primeira sincronização (zero ou último NSU conhecido);
3. regra final das pastas de canceladas/substituídas;
4. alcance da confirmação de duplicidade: arquivo, empresa ou lote.

Não informe senhas em documentos ou mensagens. Na importação em lote, o aplicativo
lê o trecho `Senha ...` do nome do PFX/P12; quando não existe, usa o padrão `1234`.
A senha é imediatamente protegida pelo Windows e nunca aparece no relatório gerado.

## Como executar

Requer Windows e Python 3.11 ou mais recente.

1. Dê duplo clique em `executar.bat`.
2. Em **Configurações**, escolha a raiz fiscal do ano, por exemplo `H:\2026`. Não escolha a pasta de Legalização onde estão os certificados.
3. Em **Empresas**, use **Importar SIEG + certificados…** para cadastrar em lote. Selecione primeiro a planilha e depois a pasta que contém os PFX/P12. Para um cadastro isolado, continue usando **Adicionar**.
   O programa pesquisa todas as subpastas e memoriza o caminho escolhido. Nos computadores da Hiperion, ele sugere `D:\01. LEGALIZAÇÃO\1. CERTIFICADORA\CERTIFICADOS` quando a pasta existe.
4. Deixe **Modo simulação** marcado para o primeiro teste.
5. Escolha mês/ano e selecione **Todas as empresas** ou uma empresa específica.
6. Marque **Emitidas / Prestados**, **Recebidas / Tomados** ou ambas e inicie o download.

O banco fica em `%LOCALAPPDATA%\NFSeLote\nfse.db` e os logs em `%LOCALAPPDATA%\NFSeLote\logs`.

Ao final da importação, o arquivo `%LOCALAPPDATA%\NFSeLote\relatorio-certificados.csv`
lista certificados cadastrados, duplicados e pendências. Ele registra apenas a origem
da senha (nome do arquivo ou padrão), nunca a senha em si.

### Mapeamento seguro por CNPJ

Como o CNPJ normalmente não aparece no nome `NUMERO BOX - RAZAO SOCIAL`, o app cria, após a primeira confirmação, um arquivo `.nfse-cnpj` dentro da pasta do cliente. Nas execuções seguintes esse marcador tem prioridade. Quando ainda não existe marcador, o app tenta uma correspondência normalizada e inequívoca da razão social. Se houver ambiguidade, a empresa falha sem arriscar gravar na pasta errada.

### Destino confirmado

Para a competência julho de 2026, por exemplo:

```text
023 - EMPRESA\02. FISCAL\ARQUIVOS\SERVIÇOS\PRESTADOS\PORTAL NACIONAL\07.2026
023 - EMPRESA\02. FISCAL\ARQUIVOS\SERVIÇOS\TOMADOS\PORTAL NACIONAL\07.2026
```

Depois de localizar com segurança a pasta da empresa em `H:\2026`, o programa cria a estrutura fiscal que estiver faltando, inclusive `PORTAL NACIONAL\MM.AAAA`. `PRESTADOS` recebe as NFS-e emitidas; `TOMADOS`, as recebidas.

Quando houver cancelamento, substituição ou manifestação, o XML do evento recebe um nome legível e fica em `PORTAL NACIONAL\MM.AAAA\Eventos`, dentro do lado correspondente à nota original.

Quando a consulta retornar zero documentos, a pasta da competência não é criada. A empresa aparece como **Sem notas** em vermelho e pode ser aberta com dois cliques no Portal Nacional para o funcionário conferir e registrar o print.

## Testes

Na pasta do projeto:

```powershell
python -m unittest discover -s tests -v
```

## Limite intencional do MVP

O primeiro download real começa no NSU 0 para garantir a competência selecionada e pode demorar. O cursor incremental por CNPJ será habilitado depois do teste controlado, mantendo a possibilidade de consultar competências retroativas.
