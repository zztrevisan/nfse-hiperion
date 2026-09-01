# Distribuição interna

## Pacote interno gratuito

O pacote `NFSe-Hiperion-1.4.0-INTERNO.zip` inclui o certificado público da
Hiperion e o arquivo `INSTALAR-CONFIANCA-HIPERION.bat`. Cada funcionário deve
executar esse instalador uma vez antes de abrir o aplicativo. A chave privada
de assinatura permanece somente no computador responsável pelas versões.

## Funcionário

1. Receba `NFSe-Hiperion.exe` pelo canal interno autorizado.
2. Abra o programa. Na primeira execução, selecione a raiz fiscal do ano, normalmente `H:\2026`.
3. Cadastre as empresas e os certificados A1 necessários.
4. Digite a senha somente na tela do aplicativo.

O computador não precisa ter Python instalado. O banco, logs e senhas protegidas ficam em `%LOCALAPPDATA%\NFSeLote` no perfil de cada usuário do Windows.

## Responsável pela versão

Execute `build.ps1` em um computador Windows com Python e internet. O resultado será criado em `release\NFSe-Hiperion-1.0.0.exe`.

Antes de distribuir:

- testar o executável em outro perfil do Windows;
- conferir acesso à unidade `H:`;
- verificar o antivírus corporativo;
- registrar a versão entregue;
- preferir assinatura digital do executável para distribuição ampla.

Para aplicar a identidade visual, coloque o ícone final em `assets\app.ico` e execute novamente `build.ps1`.
