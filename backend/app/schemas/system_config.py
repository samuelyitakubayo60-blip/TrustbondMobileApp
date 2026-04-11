from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SystemConfigItem(BaseModel):
  config_key: str
  config_value: Dict[str, Any]
  description: Optional[str] = None

  class Config:
    from_attributes = True


class SystemConfigList(BaseModel):
  items: List[SystemConfigItem]

