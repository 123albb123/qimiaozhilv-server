param(
    [Parameter(Mandatory = $true)][string]$PrivateConfig,
    [Parameter(Mandatory = $true)][string]$Artifacts,
    [Parameter(Mandatory = $true)][string]$Go,
    [Parameter(Mandatory = $true)][string]$Gcc
)
$ErrorActionPreference = 'Stop'
$config = Get-Content -Raw -LiteralPath $PrivateConfig | ConvertFrom-Json
if ($config.mysqlHost -ne '192.168.1.22:13360' -or
    $config.redisHost -ne '192.168.1.22:16380' -or
    $config.database -ne 'mhq_race_live' -or $config.password.Length -lt 32) {
    throw 'Only the explicitly provisioned disposable race database is allowed.'
}
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$artifactsPath = (Resolve-Path -LiteralPath $Artifacts).Path
$testBinary = Join-Path $artifactsPath 'race-game-20261020.test.exe'
$gameBinary = Join-Path $artifactsPath 'race-game-20261020.exe'
foreach ($binary in @($testBinary, $gameBinary)) {
    $info = & $Go version -m $binary
    if ($LASTEXITCODE -ne 0 -or -not ($info -match '-race=true')) {
        throw "A race-instrumented binary is required: $binary"
    }
}
$testLog = Join-Path $artifactsPath 'race-isolated-root-20261020.jsonl'
if (Test-Path -LiteralPath $testLog) { throw 'Refusing to overwrite previous evidence.' }
$env:PATH = (Split-Path $Gcc) + ';' + (Split-Path $Go) + ';' + $env:PATH
$env:MHQ_MYSQL_DSN = "root:$($config.password)@tcp($($config.mysqlHost))/$($config.database)?charset=utf8mb4&collation=utf8mb4_bin&parseTime=true&loc=Local"
$env:MHQ_TEST_MYSQL_DSN = $env:MHQ_MYSQL_DSN
$env:MHQ_REDIS_ADDR = $config.redisHost
$env:MHQ_REDIS_PASSWORD = $config.password
$env:MHQ_TEST_GM_CURRENCY_LIVE = '1'
$env:GORACE = 'halt_on_error=1'
$game = $null
$exitCode = 1
Push-Location $root
try {
    if (Get-NetTCPConnection -State Listen -LocalPort 7756 -ErrorAction SilentlyContinue) {
        throw 'Local TCP 7756 is already in use; no existing service will be stopped.'
    }
    $gameLog = Join-Path $artifactsPath 'race-isolated-game-20261020.log'
    $game = Start-Process -FilePath $gameBinary -ArgumentList @(
        '-listen', '127.0.0.1:7756', '-advertise', '127.0.0.1:7756', '-watch-config=false'
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardError $gameLog `
        -RedirectStandardOutput (Join-Path $artifactsPath 'race-isolated-game-stdout-20261020.log')
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        $game.Refresh()
        if ($game.HasExited) { throw "Isolated game exited: $($game.ExitCode)" }
        if ((Test-Path -LiteralPath $gameLog) -and
            (Select-String -Quiet -LiteralPath $gameLog -Pattern 'GM control consumer ready')) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'Isolated game readiness timed out.' }
    Write-Output 'Race game ready on local loopback; running root tests with isolated MySQL.'
    & $Go tool test2json -t -p mhqserver $testBinary '-test.v' '-test.count=1' '-test.timeout=45m' *> $testLog
    $exitCode = $LASTEXITCODE
    $game.Refresh()
    if ($game.HasExited -or (Select-String -Quiet -LiteralPath $gameLog -Pattern 'WARNING: DATA RACE')) {
        $exitCode = 66
    }
    Set-Content -LiteralPath (Join-Path $artifactsPath 'race-isolated-root-20261020.exit') -Value $exitCode
    Write-Output "Root test exit: $exitCode"
}
finally {
    if ($null -ne $game) {
        $game.Refresh()
        if (-not $game.HasExited) { $game | Stop-Process }
    }
    Pop-Location
}
exit $exitCode
