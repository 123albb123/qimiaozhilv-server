param(
    [Parameter(Mandatory=$true)][string]$InputDll,
    [Parameter(Mandatory=$true)][string]$OutputDll,
    [Parameter(Mandatory=$true)][string]$CecilDll
)
# Only the independently inspected qimiaozhilv-client.zip Hotfix build.
$ErrorActionPreference = 'Stop'
$expected = '08E774A4A8D2E667C4D1309DC6DF80C3DFDC083026C835DD0C9EE9794A629497'
if ((Get-FileHash -LiteralPath $InputDll -Algorithm SHA256).Hash -ne $expected) { throw 'Unsupported input DLL' }
if (Test-Path -LiteralPath $OutputDll) { throw 'Output must be a new independent file' }
Add-Type -LiteralPath $CecilDll
function Get-Types($types) {
    foreach ($type in $types) { $type; Get-Types $type.NestedTypes }
}
function Get-Body($method, [int]$skip=0) {
    if (-not $method.HasBody) { return '<no body>' }
    $instructions=@($method.Body.Instructions | Select-Object -Skip $skip)
    $indexes=@{}
    for ($i=0; $i -lt $instructions.Count; $i++) { $indexes[[int]$instructions[$i].Offset]=$i }
    $rows=foreach ($instruction in $instructions) {
        $value=$instruction.Operand
        $operand=''
        if ($value -is [Mono.Cecil.Cil.Instruction]) { $operand='target:'+$indexes[[int]$value.Offset] }
        elseif ($value -is [Mono.Cecil.Cil.Instruction[]]) { $operand=($value | ForEach-Object {$indexes[[int]$_.Offset]}) -join ',' }
        elseif ($value -is [Mono.Cecil.MemberReference]) { $operand=$value.FullName }
        elseif ($null -ne $value) { $operand=[string]$value }
        [string]$instruction.OpCode+':'+$operand
    }
    $handlers=foreach ($h in $method.Body.ExceptionHandlers) {
        $parts=foreach ($point in @($h.TryStart,$h.TryEnd,$h.HandlerStart,$h.HandlerEnd,$h.FilterStart)) {
            if ($null -eq $point) { 'end' } else { $indexes[[int]$point.Offset] }
        }
        [string]$h.HandlerType+':'+[string]$h.CatchType+':'+($parts -join ',')
    }
    ($rows -join "`n")+"`nlocals:"+(($method.Body.Variables | ForEach-Object {$_.VariableType.FullName}) -join ';')+"`nhandlers:"+($handlers -join ';')
}
function Get-Bodies($module) {
    $result=@{}
    foreach ($type in (Get-Types $module.Types)) {
        foreach ($method in $type.Methods) { $result[$method.FullName]=Get-Body $method }
    }
    return $result
}
function Get-Definitions($module) {
    ((Get-Types $module.Types | ForEach-Object {
        $_.FullName+'|'+$_.Attributes+'|'+$_.BaseType+'|'+
        (($_.Fields | ForEach-Object {$_.FullName+'|'+$_.Attributes}) -join ';')+'|'+
        (($_.Methods | ForEach-Object {$_.FullName+'|'+$_.Attributes+'|'+$_.ImplAttributes}) -join ';')
    }) -join "`n")
}
$module=[Mono.Cecil.ModuleDefinition]::ReadModule($InputDll)
try {
    $before=Get-Bodies $module
    $definitions=Get-Definitions $module
    $types=@(Get-Types $module.Types)
    $cache=@($types | Where-Object {$_.FullName -eq 'ET.ServerShopPriceCache'})
    $method=@($cache.Methods | Where-Object {$_.Name -eq 'ApplyMarketDescriptions'})
    $market=@($types | Where-Object {$_.FullName -eq 'Cal.DataTable.MarketBase'})
    $helper=@($types | Where-Object {$_.FullName -eq 'ET.DataTableHelper'})
    if ($method.Count -ne 1 -or $market.Count -ne 1 -or $helper.Count -ne 1) { throw 'Unexpected shop types' }
    $method=$method[0]
    $market=$market[0]
    $getItem=@($method.Body.Instructions | Where-Object {
        $_.Operand -is [Mono.Cecil.MethodReference] -and $_.Operand.Name -eq 'get_Item' -and
        $_.Operand.DeclaringType -is [Mono.Cecil.GenericInstanceType] -and
        $_.Operand.DeclaringType.GenericArguments.Count -eq 1 -and
        $_.Operand.DeclaringType.GenericArguments[0].FullName -eq 'System.Int32'
    })
    $get=@($helper.Methods | Where-Object {
        $_.Name -eq 'Get' -and $_.GenericParameters.Count -eq 1 -and
        $_.Parameters.Count -eq 1 -and $_.Parameters[0].ParameterType.FullName -eq 'System.Int32'
    })
    $item=@($market.Fields | Where-Object {$_.Name -eq 'ItemId' -and $_.FieldType.FullName -eq 'System.Int32'})
    if ($getItem.Count -ne 1 -or $get.Count -ne 1 -or $item.Count -ne 1) { throw 'Unexpected original description mapping' }
    $generic=[Mono.Cecil.GenericInstanceMethod]::new($get[0])
    $generic.GenericArguments.Add($market)
    $readMarket=[Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Call,$generic)
    $readItem=[Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldfld,$item[0])
    $il=$method.Body.GetILProcessor()
    $il.InsertAfter($getItem[0],$readMarket)
    $il.InsertAfter($readMarket,$readItem)
    $module.Write($OutputDll)
    $verified=[Mono.Cecil.ModuleDefinition]::ReadModule($OutputDll)
    try {
        if ($module.Mvid -ne $verified.Mvid -or $definitions -cne (Get-Definitions $verified)) { throw 'Definitions changed' }
        $after=Get-Bodies $verified
        if ((($before.Keys | Sort-Object) -join "`n") -cne (($after.Keys | Sort-Object) -join "`n")) { throw 'Method inventory changed' }
        $changed=@($before.Keys | Where-Object {$before[$_] -cne $after[$_]})
        if ($changed.Count -ne 1 -or $changed[0] -ne $method.FullName) { throw 'Unrelated method body changed' }
        $verifiedMethod=Get-Types $verified.Types | Where-Object {$_.FullName -eq 'ET.ServerShopPriceCache'} | ForEach-Object {$_.Methods} | Where-Object {$_.Name -eq 'ApplyMarketDescriptions'}
        $inserted=@($verifiedMethod.Body.Instructions | Where-Object {
            $_.Operand -is [Mono.Cecil.GenericInstanceMethod] -and $_.Operand.Name -eq 'Get' -and
            $_.Operand.GenericArguments[0].FullName -eq 'Cal.DataTable.MarketBase'
        })
        if ($inserted.Count -ne 1) { throw 'Expected one inserted MarketBase lookup' }
        $index=$verifiedMethod.Body.Instructions.IndexOf($inserted[0])
        $fieldInstruction=$verifiedMethod.Body.Instructions[$index+1]
        if ($fieldInstruction.OpCode -ne [Mono.Cecil.Cil.OpCodes]::Ldfld -or $fieldInstruction.Operand.FullName -ne $item[0].FullName) { throw 'Incorrect ItemId projection' }
        $verifiedMethod.Body.Instructions.Remove($fieldInstruction) | Out-Null
        $verifiedMethod.Body.Instructions.Remove($inserted[0]) | Out-Null
        if ((Get-Body $verifiedMethod) -cne $before[$method.FullName]) { throw 'Original description control flow changed' }
        [pscustomobject]@{MethodsCompared=$before.Count; Changed=$method.FullName; AddedInstructions=2; Sha256=(Get-FileHash -LiteralPath $OutputDll -Algorithm SHA256).Hash.ToLower()} | ConvertTo-Json
    } finally { $verified.Dispose() }
} finally { $module.Dispose() }
