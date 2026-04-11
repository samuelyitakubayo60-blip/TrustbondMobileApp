from typing import Optional

from pydantic import BaseModel


class LocationResponse(BaseModel):
    location_id: int
    location_type: str
    location_name: str
    parent_location_id: Optional[int] = None
    centroid_lat: Optional[float] = None
    centroid_long: Optional[float] = None
    is_active: bool = True

    class Config:
        from_attributes = True
