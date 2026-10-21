param([Parameter(Mandatory=$true)][string]$InputDll,[Parameter(Mandatory=$true)][string]$OutputDll,[Parameter(Mandatory=$true)][string]$CecilDll)
$ErrorActionPreference='Stop'
if((Get-FileHash -LiteralPath $InputDll -Algorithm SHA256).Hash.ToLower() -ne '6d11f836d56f26e8a441347eed43920c8781a3d62c9270b1c023aeca7199cd7a'){throw 'Unsupported input DLL'}
if(Test-Path -LiteralPath $OutputDll){throw 'Output must be a new independent file'}
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
 $cache=$types|Where-Object {$_.FullName -eq 'ET.ServerShopPriceCache'}
 $method=@($cache.Methods|Where-Object {$_.Name -eq 'LoadMarket'})
 $desc=@($cache.Methods|Where-Object {$_.Name -eq 'ApplyMarketDescriptions'})
 if($method.Count -ne 1 -or $desc.Count -ne 1){throw 'Expected exact existing market methods'}
 $method=$method[0]
 $getter=@($method.Body.Instructions|Where-Object {$_.Operand -is [Mono.Cecil.MethodReference] -and $_.Operand.Name -eq 'get_Item'})
 if($getter.Count -ne 3){throw 'Expected three LoadMarket list reads'}
 $lookup=@($desc[0].Body.Instructions|Where-Object {$_.Operand -is [Mono.Cecil.GenericInstanceMethod] -and $_.Operand.Name -eq 'Get' -and $_.Operand.GenericArguments[0].FullName -eq 'Cal.DataTable.MarketBase'})
 if($lookup.Count -ne 1){throw 'Expected audited description config lookup'}
 $projection=$desc[0].Body.Instructions[$desc[0].Body.Instructions.IndexOf($lookup[0])+1]
 if($projection.OpCode -ne [Mono.Cecil.Cil.OpCodes]::Ldfld -or $projection.Operand.Name -ne 'ItemId'){throw 'Expected ItemId projection'}
 if($method.Body.Instructions[$method.Body.Instructions.IndexOf($getter[0])+1].OpCode -ne [Mono.Cecil.Cil.OpCodes]::Stelem_I4){throw 'Expected cache key store'}
 $read=[Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Call,$lookup[0].Operand)
 $item=[Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldfld,$projection.Operand)
 $il=$method.Body.GetILProcessor()
 $il.InsertAfter($getter[0],$read)
 $il.InsertAfter($read,$item)

 $module.Write($OutputDll)
 $verified=[Mono.Cecil.ModuleDefinition]::ReadModule($OutputDll)
 try {
  if($module.Mvid -ne $verified.Mvid -or $definitions -cne (Get-Definitions $verified)){throw 'Definitions changed'}
  $after=Get-Bodies $verified
  if((($before.Keys|Sort-Object)-join "`n") -cne (($after.Keys|Sort-Object)-join "`n")){throw 'Method inventory changed'}
  $changed=@($before.Keys|Where-Object {$before[$_] -cne $after[$_]})
  if($changed.Count -ne 1 -or $changed[0] -cne $method.FullName){throw 'Unrelated method changed'}
  $vm=Get-Types $verified.Types|ForEach-Object {$_.Methods}|Where-Object {$_.FullName -ceq $method.FullName}
  $added=@($vm.Body.Instructions|Where-Object {$_.Operand -is [Mono.Cecil.GenericInstanceMethod] -and $_.Operand.Name -eq 'Get' -and $_.Operand.GenericArguments[0].FullName -eq 'Cal.DataTable.MarketBase'})
  if($added.Count -ne 1){throw 'Expected one config-to-item projection'}
  $vm.Body.Instructions.Remove($vm.Body.Instructions[$vm.Body.Instructions.IndexOf($added[0])+1])|Out-Null
  $vm.Body.Instructions.Remove($added[0])|Out-Null
  if((Get-Body $vm) -cne $before[$method.FullName]){throw 'Original control flow changed'}
  [pscustomobject]@{MethodsCompared=$before.Count;Changed=$method.FullName;AddedInstructions=2;Sha256=(Get-FileHash -LiteralPath $OutputDll -Algorithm SHA256).Hash.ToLower()}|ConvertTo-Json
 } finally {$verified.Dispose()}
} finally {$module.Dispose()}
