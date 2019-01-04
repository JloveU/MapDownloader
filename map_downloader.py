import os
import sys
import argparse
import requests
import tempfile
from math import sin, cos, tan, atan, sinh, pi, pow, log, radians, degrees, floor
from PIL import Image
from tqdm import trange


APP_NAME = "MapDownloader"
APP_DESCRIPTION = "Map Downloader"
APP_VERSION = "1.6.0"


URL_PATTERN_DICT = {
    "esri.satellite": "http://server.arcgisonline.com/arcgis/rest/services/world_imagery/mapserver/tile/{z}/{y}/{x}",
    "google.road": "https://mt1.google.cn/vt/lyrs=m&hl=zh-CN&x={x}&y={y}&z={z}",
    "google.satellite": "https://mt1.google.cn/vt/lyrs=s&hl=zh-CN&x={x}&y={y}&z={z}",
    "openstreetmap": "https://tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
}

OUTPUT_TILE_FILE_NAME_PATTERN_DICT = {
    "esri.satellite": "./OfflineMap/Tile/esri/esri_100-2-{z}-{x}-{y}.jpg",
    "google.road": "./OfflineMap/Tile/google/googleroad_100-2-{z}-{x}-{y}.jpg",
    "google.satellite": "./OfflineMap/Tile/google/googlesatellite_100-2-{z}-{x}-{y}.jpg",
    "openstreetmap": "./OfflineMap/Tile/openstreetmap/openstreetmap_100-2-{z}-{x}-{y}.png",
}

OUTPUT_MOSAIC_FILE_NAME_PATTERN_DICT = {
    "esri.satellite": "./OfflineMap/Mosaic/esri/esri_100-2-{z}-{x_min}_{x_max}-{y_min}_{y_max}.jpg",
    "google.road": "./OfflineMap/Mosaic/google/googleroad_100-2-{z}-{x_min}_{x_max}-{y_min}_{y_max}.jpg",
    "google.satellite": "./OfflineMap/Mosaic/google/googlesatellite_100-2-{z}-{x_min}_{x_max}-{y_min}_{y_max}.jpg",
    "openstreetmap": "./OfflineMap/Mosaic/openstreetmap/openstreetmap_100-2-{z}-{x_min}_{x_max}-{y_min}_{y_max}.jpg",
}


def latlng2tile(longitude, latitude, z):
    n = pow(2, z)
    x = ((longitude + 180.0) / 360.0) * n
    latitude_radian = radians(latitude)
    y = (1.0 - (log(tan(latitude_radian) + 1.0 / cos(latitude_radian)) / pi)) / 2.0 * n

    return floor(x), floor(y)


def tile2latlng(x, y, z):
    n = pow(2, z)
    longitude = x / n * 360.0 - 180.0
    latitude_radian = atan(sinh(pi * (1.0 - 2.0 * y / n)))
    latitude = degrees(latitude_radian)

    # latitude = min(max(latitude, -85.0), 85.0)

    return longitude, latitude


def download_tile(x, y, z, provider):
    file_name = OUTPUT_TILE_FILE_NAME_PATTERN_DICT[provider].format(x=x, y=y, z=z)
    if os.path.exists(file_name):
        return

    dir_name, _ = os.path.split(file_name)
    os.makedirs(dir_name, exist_ok=True)

    url = URL_PATTERN_DICT[provider].format(x=x, y=y, z=z)
    response = requests.get(url)

    with open(file_name, "wb") as file:
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                file.write(chunk)
                file.flush()


def mosaic_tiles(x_min, x_max, y_min, y_max, z, provider):
    assert(0 <= x_min)
    assert(0 <= x_max)
    assert(0 <= y_min)
    assert(0 <= y_max)
    assert(x_min <= x_max)
    assert(y_min <= y_max)
    assert(0 <= z)

    mosaic_image_width, mosaic_image_height = (x_max - x_min + 1) * 256, (y_max - y_min + 1) * 256
    mosaic_image = Image.new("RGB", (mosaic_image_width, mosaic_image_height))

    for x in trange(x_min, x_max + 1, desc="Mosaic tiles (zoom level {})".format(z)):
        for y in range(y_min, y_max + 1):
            tile_file_name = OUTPUT_TILE_FILE_NAME_PATTERN_DICT[provider].format(x=x, y=y, z=z)
            if os.path.exists(tile_file_name):
                try:
                    tile_image = Image.open(tile_file_name)
                    mosaic_image.paste(tile_image, (256 * (x - x_min), 256 * (y - y_min)))
                    tile_image.close()
                except Exception as e:
                    print("Bad image: {}".format(tile_file_name))
                    continue

    mosaic_file_name = OUTPUT_MOSAIC_FILE_NAME_PATTERN_DICT[provider].format(x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max, z=z)
    dir_name, _ = os.path.split(mosaic_file_name)
    os.makedirs(dir_name, exist_ok=True)
    mosaic_image.save(mosaic_file_name)
    mosaic_image.close()

    base_name, extension = os.path.splitext(mosaic_file_name)
    temp_file_name = base_name + "_temp" + extension
    os.rename(mosaic_file_name, temp_file_name)
    longitude_min, latitude_max = tile2latlng(x_min, y_min, z)
    longitude_max, latitude_min = tile2latlng(x_max + 1, y_max + 1, z)
    print("Actual latlon bound: [[{:.7f}, {:.7f}], [{:.7f}, {:.7f}]]".format(latitude_min, longitude_min, latitude_max, longitude_max))
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file_name = os.path.join(temp_dir, "input.txt")
            output_file_name = os.path.join(temp_dir, "output.txt")
            with open(input_file_name, "wt") as file:
                file.write("{:.7f} {:.7f}\n{:.7f} {:.7f}\n".format(longitude_min, latitude_max, longitude_max, latitude_min))
            command_string = "gdaltransform -s_srs EPSG:4326 -t_srs EPSG:3857 -output_xy < \"{input_file_name}\" > \"{output_file_name}\"".format(input_file_name=input_file_name, output_file_name=output_file_name)
            print(command_string)
            os.system(command_string)
            with open(output_file_name, "rt") as file:
                geo_x_min_string, geo_y_max_string = tuple(file.readline().strip().split(" "))
                geo_x_max_string, geo_y_min_string = tuple(file.readline().strip().split(" "))
                geo_x_min, geo_y_max = float(geo_x_min_string), float(geo_y_max_string)
                geo_x_max, geo_y_min = float(geo_x_max_string), float(geo_y_min_string)
    except Exception:
        os.rename(temp_file_name, mosaic_file_name)
    else:
        output_format = "JPEG" if (extension == ".jpg") else "GTIFF"
        command_string = "gdal_translate -of {output_format} -a_srs EPSG:3857 -a_ullr {ulx} {uly} {lrx} {lry} \"{input_file_name}\" \"{output_file_name}\"".format(output_format=output_format, ulx=geo_x_min, uly=geo_y_max, lrx=geo_x_max, lry=geo_y_min, input_file_name=temp_file_name, output_file_name=mosaic_file_name)
        print(command_string)
        os.system(command_string)
        os.remove(temp_file_name)
        open(mosaic_file_name + ".latlonbound.txt", "wt").write("[[{:.7f}, {:.7f}], [{:.7f}, {:.7f}]]".format(latitude_min, longitude_min, latitude_max, longitude_max))


def download_tiles(x_min, x_max, y_min, y_max, z, provider, mosaic=True):
    assert(0 <= x_min)
    assert(0 <= x_max)
    assert(0 <= y_min)
    assert(0 <= y_max)
    assert(x_min <= x_max)
    assert(y_min <= y_max)
    assert(0 <= z)

    for x in trange(x_min, x_max + 1, desc="Download tiles (zoom level {})".format(z)):
        for y in range(y_min, y_max + 1):
            download_tile(x, y, z, provider)

    if mosaic:
        mosaic_tiles(x_min, x_max, y_min, y_max, z, provider)


def download_tiles_by_latlng_range(longitude_min, longitude_max, latitude_min, latitude_max, z, provider, mosaic=True):
    assert(-180.0 <= longitude_min <= 180.0)
    assert(-180.0 <= longitude_max <= 180.0)
    assert(-90.0 <= latitude_min <= 90.0)
    assert(-90.0 <= latitude_max <= 90.0)
    assert(longitude_min <= longitude_max)
    assert(latitude_min <= latitude_max)
    assert(0 <= z)

    x_min, y_min = latlng2tile(longitude_min, latitude_max, z)
    x_max, y_max = latlng2tile(longitude_max, latitude_min, z)
    download_tiles(x_min, x_max, y_min, y_max, z, provider, mosaic)


def get_args():
    arg_parser = argparse.ArgumentParser(prog=APP_NAME, description=APP_DESCRIPTION)
    arg_parser.add_argument("-v", "--version", action="version", version="%(prog)s {}".format(APP_VERSION))
    arg_parser.add_argument("-l", "--longitude-min", help="The min longitude (default: '%(default)s').", type=float, default=116.3577)
    arg_parser.add_argument("-r", "--longitude-max", help="The max longitude (default: '%(default)s').", type=float, default=116.4250)
    arg_parser.add_argument("-b", "--latitude-min", help="The min latitude (default: '%(default)s').", type=float, default=39.8980)
    arg_parser.add_argument("-t", "--latitude-max", help="The max latitude (default: '%(default)s').", type=float, default=39.9272)
    arg_parser.add_argument("-z", "--z-min", help="The min zoom level (default: '%(default)s').", type=int, default=0)
    arg_parser.add_argument("-x", "--z-max", help="The max zoom level (default: '%(default)s').", type=int, default=16)
    arg_parser.add_argument("-p", "--provider", help="The map provider (default: '%(default)s').", default="esri.satellite")
    arg_parser.add_argument("-m", "--mosaic", help="Whether to mosaic the map (default: '%(default)s').", action="store_true", default=True)

    return arg_parser.parse_args()


def main():
    args = get_args()

    longitude_min = args.longitude_min
    longitude_max = args.longitude_max
    latitude_min = args.latitude_min
    latitude_max = args.latitude_max
    z_min = args.z_min
    z_max = args.z_max
    provider = args.provider
    mosaic = args.mosaic

    for z in range(z_min, z_max + 1):
        download_tiles_by_latlng_range(longitude_min, longitude_max, latitude_min, latitude_max, z, provider, mosaic)

    print("Done!")


if __name__ == "__main__":
    main()
