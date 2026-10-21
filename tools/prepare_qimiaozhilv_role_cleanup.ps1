param([Parameter(Mandatory=$true)][string]$InputDll,[Parameter(Mandatory=$true)][string]$OutputDll,[Parameter(Mandatory=$true)][string]$CecilDll)
$ErrorActionPreference='Stop'
if((Get-FileHash -LiteralPath $InputDll -Algorithm SHA256).Hash.ToLower() -ne '708bdcd6e971d608cf688356323767eec4022beff3019878bdca0ba3221d0b30'){throw 'Unsupported input DLL'}
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
 $method=@(Get-Types $module.Types|Where-Object {$_.FullName -eq 'ET.CreateRoleUnit'}|ForEach-Object {$_.Methods}|Where-Object {$_.Name -eq 'set_gameObject'})
 if($method.Count -ne 1){throw 'Expected one model setter'}
 $method=$method[0]
 if($method.Body.Instructions[2].OpCode -ne [Mono.Cecil.Cil.OpCodes]::Stfld -or $method.Body.Instructions[2].Operand.Name -ne '_go'){throw 'Expected initial model assignment'}
 $next=$method.Body.Instructions[3]
 $guard=@([Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ldarg_1),[Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Brtrue,$next),[Mono.Cecil.Cil.Instruction]::Create([Mono.Cecil.Cil.OpCodes]::Ret))
 $il=$method.Body.GetILProcessor()
 foreach($instruction in $guard){$il.InsertBefore($next,$instruction)}

 $module.Write($OutputDll)
 $verified=[Mono.Cecil.ModuleDefinition]::ReadModule($OutputDll)
 try {
  if($module.Mvid -ne $verified.Mvid -or $definitions -cne (Get-Definitions $verified)){throw 'Definitions changed'}
  $after=Get-Bodies $verified
  if((($before.Keys|Sort-Object)-join "`n") -cne (($after.Keys|Sort-Object)-join "`n")){throw 'Method inventory changed'}
  $changed=@($before.Keys|Where-Object {$before[$_] -cne $after[$_]})
  if($changed.Count -ne 1 -or $changed[0] -cne $method.FullName){throw 'Unrelated method changed'}
  $vm=Get-Types $verified.Types|ForEach-Object {$_.Methods}|Where-Object {$_.FullName -ceq $method.FullName}
  if($vm.Body.Instructions[3].OpCode -ne [Mono.Cecil.Cil.OpCodes]::Ldarg_1 -or $vm.Body.Instructions[4].OpCode -ne [Mono.Cecil.Cil.OpCodes]::Brtrue -or $vm.Body.Instructions[5].OpCode -ne [Mono.Cecil.Cil.OpCodes]::Ret -or $vm.Body.Instructions[4].Operand -ne $vm.Body.Instructions[6]){throw 'Invalid null guard'}
  for($i=0;$i -lt 3;$i++){$vm.Body.Instructions.RemoveAt(3)}
  if((Get-Body $vm) -cne $before[$method.FullName]){throw 'Original control flow changed'}
  [pscustomobject]@{MethodsCompared=$before.Count;Changed=$method.FullName;AddedInstructions=3;Sha256=(Get-FileHash -LiteralPath $OutputDll -Algorithm SHA256).Hash.ToLower()}|ConvertTo-Json
 } finally {$verified.Dispose()}
} finally {$module.Dispose()}
