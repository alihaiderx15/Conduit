from __future__ import annotations
from typing import Any, Mapping
from .errors import ToolValidationError

def validate_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, Mapping): raise ToolValidationError("Tool arguments must be an object.")
    props=schema.get("properties",{}); required=schema.get("required",[])
    for field in required:
        if field not in arguments: raise ToolValidationError(f"Missing required argument: {field}")
    unknown=set(arguments)-set(props)
    if unknown: raise ToolValidationError(f"Unknown argument(s): {', '.join(sorted(unknown))}")
    out={}
    for field,value in arguments.items():
        spec=props.get(field,{})
        expected=spec.get("type")
        checks={"string":lambda x:isinstance(x,str),"integer":lambda x:isinstance(x,int) and not isinstance(x,bool),"number":lambda x:isinstance(x,(int,float)) and not isinstance(x,bool),"boolean":lambda x:isinstance(x,bool),"array":lambda x:isinstance(x,list),"object":lambda x:isinstance(x,Mapping)}
        if expected in checks and not checks[expected](value): raise ToolValidationError(f"Argument '{field}' must be of type {expected}.")
        if "enum" in spec and value not in spec["enum"]: raise ToolValidationError(f"Argument '{field}' has an unsupported value.")
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            if spec.get("minimum") is not None and value<spec["minimum"]: raise ToolValidationError(f"Argument '{field}' must be at least {spec['minimum']}.")
            if spec.get("maximum") is not None and value>spec["maximum"]: raise ToolValidationError(f"Argument '{field}' must be at most {spec['maximum']}.")
        out[field]=value
    return out
