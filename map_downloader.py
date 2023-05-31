import os
import sys
import argparse
import logging
import requests
import tempfile
import time
import PIL
import PIL.Image
import tqdm
import tqdm.contrib.concurrent
from math import sin, cos, tan, atan, sinh, pi, pow, log, radians, degrees, floor


APP_NAME = "MapDownloader"
APP_DESCRIPTION = "Map Downloader"
APP_VERSION = "1.8.0"


URL_PATTERN_DICT = {
    "esri.satellite": "http://server.arcgisonline.com/arcgis/rest/services/world_imagery/mapserver/tile/{z}/{y}/{x}",
    "google.road": "https://mt1.google.cn/vt/lyrs=m&hl=zh-CN&x={x}&y={y}&z={z}",
    "google.satellite": "https://mt1.google.cn/vt/lyrs=s&hl=zh-CN&x={x}&y={y}&z={z}",
    "openstreetmap": "https://tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
}

OUTPUT_TILE_FILE_NAME_PATTERN_DICT = {
    "esri.satellite": "./OfflineMap/Tile/esri-satellite/{z}/{x}/{y}.jpg",
    "google.road": "./OfflineMap/Tile/google-road/{z}/{x}/{y}.jpg",
    "google.satellite": "./OfflineMap/Tile/google-satellite/{z}/{x}/{y}.jpg",
    "openstreetmap": "./OfflineMap/Tile/openstreetmap/{z}/{x}/{y}.png",
}

OUTPUT_MOSAIC_FILE_NAME_PATTERN_DICT = {
    "esri.satellite": "./OfflineMap/Mosaic/esri-satellite-{z}-{x_min}_{x_max}-{y_min}_{y_max}.jpg",
    "google.road": "./OfflineMap/Mosaic/google-road-{z}-{x_min}_{x_max}-{y_min}_{y_max}.jpg",
    "google.satellite": "./OfflineMap/Mosaic/google-satellite-{z}-{x_min}_{x_max}-{y_min}_{y_max}.jpg",
    "openstreetmap": "./OfflineMap/Mosaic/openstreetmap-{z}-{x_min}_{x_max}-{y_min}_{y_max}.jpg",
}


work_time = 120
sleep_time = 30


def latlon2tile(longitude, latitude, z):
    n = pow(2, z)
    x = ((longitude + 180.0) / 360.0) * n
    latitude_radian = radians(latitude)
    y = (1.0 - (log(tan(latitude_radian) + 1.0 / cos(latitude_radian)) / pi)) / 2.0 * n

    return floor(x), floor(y)


def tile2latlon(x, y, z):
    n = pow(2, z)
    longitude = x / n * 360.0 - 180.0
    latitude_radian = atan(sinh(pi * (1.0 - 2.0 * y / n)))
    latitude = degrees(latitude_radian)

    # latitude = min(max(latitude, -85.0), 85.0)

    return longitude, latitude


def download_tile(x, y, z, provider, begin_time=None):
    while (int(time.monotonic() - begin_time) % (work_time + sleep_time)) > work_time:
        time.sleep(1)

    url_pattern = provider["url"] if isinstance(provider, dict) else URL_PATTERN_DICT[provider]
    output_tile_file_name_pattern = provider["output_tile"] if isinstance(provider, dict) else OUTPUT_TILE_FILE_NAME_PATTERN_DICT[provider]

    file_name = output_tile_file_name_pattern.format(x=x, y=y, z=z)
    if os.path.exists(file_name):
        return

    dir_name, _ = os.path.split(file_name)
    os.makedirs(dir_name, exist_ok=True)

    url = url_pattern.format(x=x, y=y, z=z)

    wait_time = 1
    while True:
        try:
            response = requests.get(url)
            break
        except Exception as e:
            logging.critical(f"Failed to download '{url}' to '{file_name}': {e}")
            logging.critical(f"Wait {wait_time} seconds ...")
            time.sleep(wait_time)
            wait_time = min(wait_time * 2, 1 * 60 * 60)

    with open(file_name, "wb") as file:
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                file.write(chunk)
                # file.flush()


def download_tile_(param):
    download_tile(*param)


def mosaic_tiles(x_min, x_max, y_min, y_max, z, provider):
    assert(0 <= x_min)
    assert(0 <= x_max)
    assert(0 <= y_min)
    assert(0 <= y_max)
    assert(x_min <= x_max)
    assert(y_min <= y_max)
    assert(0 <= z)

    output_tile_file_name_pattern = provider["output_tile"] if isinstance(provider, dict) else OUTPUT_TILE_FILE_NAME_PATTERN_DICT[provider]
    output_mosaic_file_name_pattern = provider["output_mosaic"] if isinstance(provider, dict) else OUTPUT_MOSAIC_FILE_NAME_PATTERN_DICT[provider]

    mosaic_image_width, mosaic_image_height = (x_max - x_min + 1) * 256, (y_max - y_min + 1) * 256
    mosaic_image = PIL.Image.new("RGB", (mosaic_image_width, mosaic_image_height))

    logging.info(f"Mosaic tiles (zoom level {z})")

    for x in tqdm.trange(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            tile_file_name = output_tile_file_name_pattern.format(x=x, y=y, z=z)
            if os.path.exists(tile_file_name):
                try:
                    tile_image = PIL.Image.open(tile_file_name)
                    mosaic_image.paste(tile_image, (256 * (x - x_min), 256 * (y - y_min)))
                    tile_image.close()
                except Exception as e:
                    logging.warning(f"Bad image: {tile_file_name}")
                    continue

    mosaic_file_name = output_mosaic_file_name_pattern.format(x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max, z=z)
    dir_name, _ = os.path.split(mosaic_file_name)
    os.makedirs(dir_name, exist_ok=True)
    mosaic_image.save(mosaic_file_name)
    mosaic_image.close()

    base_name, extension = os.path.splitext(mosaic_file_name)
    temp_file_name = base_name + "_temp" + extension
    os.rename(mosaic_file_name, temp_file_name)
    longitude_min, latitude_max = tile2latlon(x_min, y_min, z)
    longitude_max, latitude_min = tile2latlon(x_max + 1, y_max + 1, z)
    logging.info(f"Actual latlon bound: [[{latitude_min:.7f}, {longitude_min:.7f}], [{latitude_max:.7f}, {longitude_max:.7f}]]")
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file_name = os.path.join(temp_dir, "input.txt")
            output_file_name = os.path.join(temp_dir, "output.txt")
            with open(input_file_name, "wt") as file:
                file.write(f"{longitude_min:.7f} {latitude_max:.7f}\n{longitude_max:.7f} {latitude_min:.7f}\n")
            command_string = f"gdaltransform -s_srs EPSG:4326 -t_srs EPSG:3857 -output_xy < \"{input_file_name}\" > \"{output_file_name}\""
            logging.info(command_string)
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
        command_string = f"gdal_translate -of {output_format} -a_srs EPSG:3857 -a_ullr {geo_x_min} {geo_y_max} {geo_x_max} {geo_y_min} \"{temp_file_name}\" \"{mosaic_file_name}\""
        logging.info(command_string)
        os.system(command_string)
        os.remove(temp_file_name)
        open(mosaic_file_name + ".latlonbound.txt", "wt").write(f"[[{latitude_min:.7f}, {longitude_min:.7f}], [{latitude_max:.7f}, {longitude_max:.7f}]]")


def download_tiles(x_min, x_max, y_min, y_max, z, provider, mosaic=True):
    assert(0 <= x_min)
    assert(0 <= x_max)
    assert(0 <= y_min)
    assert(0 <= y_max)
    assert(x_min <= x_max)
    assert(y_min <= y_max)
    assert(0 <= z)

    x_count = x_max - x_min + 1
    y_count = y_max - y_min + 1
    total_count = x_count * y_count

    logging.info(f"Download tiles (zoom level {z})")

    begin_time = time.monotonic()
    use_concurrent = False

    if use_concurrent:
        tqdm.contrib.concurrent.process_map(download_tile_, [(x_min + (index % x_count), y_min + (index // x_count), z, provider, begin_time) for index in range(total_count)], max_workers=2, chunksize=2)
    else:
        for index in tqdm.trange(total_count):
            x = x_min + (index % x_count)
            y = y_min + (index // x_count)
            download_tile(x, y, z, provider, begin_time)

    if mosaic:
        mosaic_tiles(x_min, x_max, y_min, y_max, z, provider)


def download_tiles_by_latlon_range(longitude_min, longitude_max, latitude_min, latitude_max, z, provider, mosaic=True):
    assert(-180.0 <= longitude_min <= 180.0)
    assert(-180.0 <= longitude_max <= 180.0)
    assert(-90.0 <= latitude_min <= 90.0)
    assert(-90.0 <= latitude_max <= 90.0)
    assert(longitude_min <= longitude_max)
    assert(latitude_min <= latitude_max)
    assert(0 <= z)

    x_min, y_min = latlon2tile(longitude_min, latitude_max, z)
    x_max, y_max = latlon2tile(longitude_max, latitude_min, z)
    download_tiles(x_min, x_max, y_min, y_max, z, provider, mosaic)


def get_args():
    arg_parser = argparse.ArgumentParser(prog=APP_NAME, description=APP_DESCRIPTION)
    arg_parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {APP_VERSION}")
    arg_parser.add_argument("-l", "--longitude-min", help="The min longitude (default: '%(default)s').", type=float, default=-179.999999)
    arg_parser.add_argument("-r", "--longitude-max", help="The max longitude (default: '%(default)s').", type=float, default=179.999999)
    arg_parser.add_argument("-b", "--latitude-min", help="The min latitude (default: '%(default)s').", type=float, default=-84.999999)
    arg_parser.add_argument("-t", "--latitude-max", help="The max latitude (default: '%(default)s').", type=float, default=84.999999)
    arg_parser.add_argument("-z", "--z-min", help="The min zoom level (default: '%(default)s').", type=int, default=0)
    arg_parser.add_argument("-x", "--z-max", help="The max zoom level (default: '%(default)s').", type=int, default=10)
    arg_parser.add_argument("-p", "--provider", help="The map provider (default: '%(default)s').", default="google.road")
    arg_parser.add_argument("-m", "--mosaic", help="Whether to mosaic the map (default: '%(default)s').", action="store_true", default=False)
    arg_parser.add_argument("--log-file", help="The log file name (default: log not saved).")
    arg_parser.add_argument("--url", help="The url pattern.")
    arg_parser.add_argument("--output-tile", help="The output tile file name pattern.")
    arg_parser.add_argument("--output-mosaic", help="The output mosaic file name pattern.")

    return arg_parser.parse_args()


def main():
    args = get_args()

    logging.basicConfig(filename=args.log_file, filemode="a", format="[%(asctime)s] [%(levelname)s] [%(module)s.%(funcName)s] %(message)s", level=logging.INFO)
    logging.info(APP_DESCRIPTION)

    longitude_min = args.longitude_min
    longitude_max = args.longitude_max
    latitude_min = args.latitude_min
    latitude_max = args.latitude_max
    z_min = args.z_min
    z_max = args.z_max
    provider = args.provider
    mosaic = args.mosaic
    url = args.url
    output_tile = args.output_tile
    output_mosaic = args.output_mosaic

    if (provider not in URL_PATTERN_DICT) and (url is not None):
        if output_tile is None:
            output_tile = "./OfflineMap/Tile/" + provider + "/{z}/{x}/{y}.jpg"
        if output_mosaic is None:
            output_mosaic = "./OfflineMap/Mosaic/" + provider + "-{z}-{x_min}_{x_max}-{y_min}_{y_max}.jpg"
        provider = {"url": url, "output_tile": output_tile, "output_mosaic": output_mosaic}

    for z in range(z_min, z_max + 1):
        download_tiles_by_latlon_range(longitude_min, longitude_max, latitude_min, latitude_max, z, provider, mosaic)

    logging.info("Done.")


if __name__ == "__main__":
    main()
