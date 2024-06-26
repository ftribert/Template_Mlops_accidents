"""Initializing and populating the DB."""

import os
import time
from pathlib import Path
from typing import Dict

from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.exc import OperationalError
from sqlalchemy import Engine
import tqdm
import pandas as pd
from dotenv import load_dotenv

from src.data.db.models import *
from src.data.db.models import Caracteristiques, Lieux, Vehicules, Users
from src.data.db.file_tasks import get_road_accident_file2model, get_dataframe

load_dotenv()  # take environment variables from .env.

PATH_RAW_FILES_DIR = os.getenv("RAW_FILES_ROOT_DIR")
host = os.getenv("POSTGRES_HOST")
database = os.getenv("POSTGRES_DB")
user = os.getenv("POSTGRES_USER")
password = os.getenv("POSTGRES_PASSWORD")
port = os.getenv("POSTGRES_PORT")
db_url = (
    "postgresql+psycopg2://{user}:{password}@{hostname}:{port}/{database_name}".format(
        hostname=host, user=user, password=password, database_name=database, port=5432
    )
)


def create_db_engine(db_url: str) -> Engine:
    return create_engine(db_url)


def init_db(engine: Engine, sleep_for: float = 30) -> None:
    """Create DB tables based on the SqlModels."""
    while True:
        try:
            print("Trying to create the DB tables")
            SQLModel.metadata.create_all(engine)
        except OperationalError:
            print("Failed... Attempting again.")
            time.sleep(sleep_for)
        except Exception:
            raise
        else:
            print("Tables created.")
            break


def _add_data_to_table(
    db_session: Session, df: pd.DataFrame, table_model: SQLModel):
    print(f"Adding data to the '{table_model.__tablename__}' table.")

    for _, row in tqdm.tqdm(df.iterrows(), total=len(df)):
        carac = table_model(**row)
        db_session.add(carac)
    db_session.commit()


def update_raw_accidents_csv_files_table(
    db_session: Session,
    files: Dict[RawRoadAccidentCsvFileNames, RawRoadAccidentsCsvFile],
) -> None:
    for road_acc_type, road_acc_file in files.items():
        print(
            f"Checking if file `{road_acc_file.file_name}` has already been processed using its md5=`{road_acc_file.md5}`"
        )
        db_table_entries = select(RawRoadAccidentsCsvFile).where(
            RawRoadAccidentsCsvFile.md5 == road_acc_file.md5
        )
        results = list(db_session.exec(db_table_entries))
        if any([r.processing_status == ProcessingStatus.processed for r in results]):
            print(
                f"File `{road_acc_file.dir_name}/`{road_acc_file.file_name}` has already been processed. Skipping..."
            )
            road_acc_file.processing_status = ProcessingStatus.processed
            continue

        print(f"Adding file `{road_acc_file.file_name}` to the DB.")
        db_session.add(road_acc_file)
    db_session.commit()
    print("Success!")


def add_data_to_db(db_session: Session, files) -> None:
    order_files = [
        RawRoadAccidentCsvFileNames.caracteristiques,
        RawRoadAccidentCsvFileNames.lieux,
        RawRoadAccidentCsvFileNames.vehicules,
        RawRoadAccidentCsvFileNames.usagers,
    ]

    for raw_csv_type in order_files:
        if not (road_acc_model := files.get(raw_csv_type)):
            continue

        if road_acc_model.processing_status == ProcessingStatus.processed:
            continue

        df = get_dataframe(road_acc_model.path)
        if raw_csv_type == RawRoadAccidentCsvFileNames.caracteristiques:
            table_model = Caracteristiques
        elif raw_csv_type == RawRoadAccidentCsvFileNames.lieux:
            table_model = Lieux
        elif raw_csv_type == RawRoadAccidentCsvFileNames.usagers:
            table_model = Users
        elif raw_csv_type == RawRoadAccidentCsvFileNames.vehicules:
            table_model = Vehicules
        else:
            raise RuntimeError(f"Unknown road accidents raw file `{raw_csv_type}`!")
        try:
            _add_data_to_table(db_session, df=df, table_model=table_model)
            road_acc_model.processing_status = ProcessingStatus.processed
        except Exception as e: # TODO use correct sqlalchemy exception
            print(f"Error while adding `{raw_csv_type}` data to the `{table_model}` table. Exception: `{e}`")
            road_acc_model.processing_status = ProcessingStatus.failed
            road_acc_model.reason = f"Exception raised: {e}"
        finally:
            db_session.add(road_acc_model)


def main():
    engine = create_db_engine(db_url=db_url)
    init_db(engine=engine)

    file2model = get_road_accident_file2model(Path(PATH_RAW_FILES_DIR))
    with Session(engine) as session:
        update_raw_accidents_csv_files_table(
            db_session=session, files=file2model
        )
        add_data_to_db(db_session=session, files=file2model)
        session.commit()

    print("Done populating the DB, taking a long siesta...")
    while True:
        time.sleep(120)


if __name__ == "__main__":
    main()
