import geopandas as gpd
from shapely.geometry import mapping, shape


def merge_polygons_by_warn(input_geojson: dict) -> dict:
    #Merge neighboring polygons in a GeoJSON-like dictionary
    #when the 'warn' property is the same.
    #Args:
    #    input_geojson (dict): Input GeoJSON as a dictionary.
    #Returns:
    #    dict: Merged GeoJSON as a dictionary.

    # Convert the GeoJSON dict to a GeoDataFrame
    gdf = gpd.GeoDataFrame.from_features(input_geojson["features"])
    
    # Check if 'warn' property exists
    if 'warn.level' not in gdf.columns:
        raise KeyError("The 'warn.level' property is missing in the GeoJSON dictionary.")

    # Group by 'warn' and merge polygons
    merged_gdf = gdf.dissolve(by='warn.level', as_index=False)

    # Convert back to GeoJSON dictionary
    merged_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": row.drop("geometry").to_dict(),
                "geometry": mapping(row.geometry)
            }
            for _, row in merged_gdf.iterrows()
        ]
    }

    return merged_geojson

