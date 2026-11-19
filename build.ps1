param([string]$Configuration='Release')
$ErrorActionPreference='Stop'
$Root=$PSScriptRoot
$env:DOTNET_CLI_HOME=Join-Path $Root 'cache/dotnet'
$env:NUGET_PACKAGES=Join-Path $Root 'cache/nuget'
$env:TEMP=Join-Path $Root 'cache/temp'
$env:TMP=$env:TEMP
$env:DOTNET_NOLOGO='1'
foreach($Directory in @($env:DOTNET_CLI_HOME,$env:NUGET_PACKAGES,$env:TEMP)){
 New-Item -ItemType Directory -Force -Path $Directory | Out-Null
}
dotnet publish (Join-Path $Root 'src/CharacterToolkit/CharacterToolkit.csproj') -c $Configuration -r win-x64 --self-contained true -o $Root
if($LASTEXITCODE -ne 0){throw 'GUI publish failed'}
dotnet publish (Join-Path $Root 'src/CharacterWorker/CharacterWorker.csproj') -c $Configuration -r win-x64 --self-contained true -o (Join-Path $Root 'runtime/worker')
if($LASTEXITCODE -ne 0){throw 'Worker publish failed'}
Write-Host (Join-Path $Root 'SekiroCharacterToolkit.exe')
