param(
  [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

$ErrorActionPreference = "Stop"

function Find-GcloudCmd {
  $list = New-Object System.Collections.Generic.List[string]

  $fromPath = (Get-Command gcloud.cmd -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
  if ($fromPath -and (Test-Path $fromPath)) { $list.Add([string]$fromPath) }

  $p1 = 'C:\Program Files\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
  if (Test-Path $p1) { $list.Add($p1) }

  $p2 = 'C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
  if (Test-Path $p2) { $list.Add($p2) }

  $uniqArr = @($list | Select-Object -Unique)
  if ($uniqArr.Count -gt 0) { return [string]$uniqArr[0] }
  return $null
}

$gcloudCmd = Find-GcloudCmd
if (-not $gcloudCmd) {
  Write-Error "gcloud.cmd not found. Install Google Cloud SDK or add it to PATH."
}

$quoted = '"' + $gcloudCmd + '"'
$argLine = ($Args | ForEach-Object {
  if ($_ -match '\s') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
}) -join ' '

cmd.exe /c "$quoted $argLine"
exit $LASTEXITCODE

