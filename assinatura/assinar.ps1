param([Parameter(Mandatory=$true)][string]$Arquivo)
$ErrorActionPreference = "Stop"
$Subject = "CN=Hiperion Assessoria Contabil - Aplicativos Internos"
$Cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object {
    $_.Subject -eq $Subject -and $_.NotAfter -gt (Get-Date)
} | Sort-Object NotAfter -Descending | Select-Object -First 1

if (-not $Cert) {
    $Cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $Subject `
        -CertStoreLocation Cert:\CurrentUser\My -HashAlgorithm SHA256 `
        -KeyAlgorithm RSA -KeyLength 3072 -NotAfter (Get-Date).AddYears(5) `
        -FriendlyName "Hiperion - Assinatura de aplicativos internos"
}

$Publico = Join-Path $PSScriptRoot "Hiperion-Assinatura-Interna.cer"
Export-Certificate -Cert $Cert -FilePath $Publico -Force | Out-Null
$Result = Set-AuthenticodeSignature -FilePath $Arquivo -Certificate $Cert -HashAlgorithm SHA256
if ($Result.Status -notin @("Valid", "UnknownError")) {
    throw "Falha ao assinar: $($Result.Status) - $($Result.StatusMessage)"
}
Write-Host "Arquivo assinado por: $($Cert.Subject)"
Write-Host "Validade: $($Cert.NotAfter)"
Write-Host "Impressao digital: $($Cert.Thumbprint)"
