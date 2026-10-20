param(
    [Parameter(Mandatory=$true)][string]$InputDll,
    [Parameter(Mandatory=$true)][string]$OutputDll,
    [Parameter(Mandatory=$true)][string]$CecilDll
)
# Only the independently inspected qimiaozhilv-client.zip HotfixView build.
$ErrorActionPreference = 'Stop'
$expected = 'DFAD86065C4963F63853AF112F8029E2728EDE4A6021CB93E5B0E7942DC32D15'
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
    $type=@(Get-Types $module.Types | Where-Object {$_.FullName -eq 'ET.InitHeadInfoEvent'})
    $head=@($type.Methods | Where-Object {$_.Name -eq 'Run'})
    if ($head.Count -ne 1) { throw 'Expected exactly one head-info Run method' }
    $head=$head[0]
    # Existing loop-finally regions stay anchored to their original instructions;
    # Get-Body below verifies their boundaries as well as the original flow.
    $scene=@($head.Body.Instructions.Operand | Where-Object {$_ -is [Mono.Cecil.FieldReference] -and $_.Name -eq 'zoneScene'} | Select-Object -Unique)
    $component=@($head.Body.Instructions.Operand | Where-Object {$_ -is [Mono.Cecil.GenericInstanceMethod] -and $_.Name -eq 'GetComponent' -and $_.GenericArguments[0].FullName -eq 'ET.UnitComponent'} | Select-Object -Unique)
    $unit=@($head.Body.Instructions.Operand | Where-Object {$_ -is [Mono.Cecil.MethodReference] -and $_.Name -eq 'get_MyUnit'} | Select-Object -Unique)
    if ($scene.Count -ne 1 -or $component.Count -ne 1 -or $unit.Count -ne 1) { throw 'Unexpected original head-info shape' }
    $first=$head.Body.Instructions[0]
    $guards=@(
        [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldarg_1),
        [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldfld,$scene[0]),
        [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Callvirt,$component[0]),
        [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Callvirt,$unit[0]),
        [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Brtrue,$first),
        [Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ret)
    )
    $il=$head.Body.GetILProcessor()
    foreach ($guard in $guards) { $il.InsertBefore($first,$guard) }
    $module.Write($OutputDll)
    $verified=[Mono.Cecil.ModuleDefinition]::ReadModule($OutputDll)
    try {
        if ($module.Mvid -ne $verified.Mvid -or $definitions -cne (Get-Definitions $verified)) { throw 'Definitions changed' }
        $after=Get-Bodies $verified
        if ((($before.Keys | Sort-Object) -join "`n") -cne (($after.Keys | Sort-Object) -join "`n")) { throw 'Method inventory changed' }
        $changed=@($before.Keys | Where-Object {$before[$_] -cne $after[$_]})
        if ($changed.Count -ne 1 -or $changed[0] -ne $head.FullName) { throw 'Unrelated method body changed' }
        $verifiedHead=Get-Types $verified.Types | Where-Object {$_.FullName -eq 'ET.InitHeadInfoEvent'} | ForEach-Object {$_.Methods} | Where-Object {$_.Name -eq 'Run'}
        if ((Get-Body $verifiedHead 6) -cne $before[$head.FullName]) { throw 'Original head-info control flow changed' }
        [pscustomobject]@{MethodsCompared=$before.Count; Changed=$head.FullName; AddedInstructions=6; Sha256=(Get-FileHash -LiteralPath $OutputDll -Algorithm SHA256).Hash.ToLower()} | ConvertTo-Json
    } finally { $verified.Dispose() }
} finally { $module.Dispose() }
