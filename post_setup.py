import os
import requests
import shutil

from CONFIG.FOLDER_STRUCTURE import *


def download_file(url, path):
    with requests.get(url, stream=True) as r:
        with open(path, 'wb') as f:
            shutil.copyfileobj(r.raw, f)


def main():
    print("Creating folders structure based on CONFIG/FOLDER_STRUCTURE.py")
    DATA_ROOT.mkdir(exist_ok=True, parents=True)
    STRUCTURE_FILES_PATH.mkdir(exist_ok=True, parents=True)
    QUERY_PATH.mkdir(exist_ok=True, parents=True)
    (QUERY_PATH / DEFAULT_NAME).mkdir(exist_ok=True, parents=True)
    FINISHED_PATH.mkdir(exist_ok=True, parents=True)

    WORK_PATH.mkdir(exist_ok=True, parents=True)
    SEQ_ATOMS_DATASET_PATH.mkdir(exist_ok=True, parents=True)
    MMSEQS_DATABASES_PATH.mkdir(exist_ok=True, parents=True)

    if not DEEPFRI_MODEL_WEIGHTS_JSON_FILE.exists():
        print(f"No model config.json file found in {DATA_ROOT / 'trained_models'}.")

        if not pathlib.Path("newest_trained_models.tar.gz").exists():
            print("Downloading model weights, approx 800MB")
            download_file(DEEPFRI_TRAINED_MODELS_DOWNLOAD_URL, 'newest_trained_models.tar.gz')

        print(f"unloading models into {DATA_ROOT / 'trained_models'} directory")
        os.system(f"tar xvzf newest_trained_models.tar.gz -C {DATA_ROOT}")
    else:
        print("Found model weights")
    print("All good and ready to go!")


if __name__ == "__main__":
    main()
