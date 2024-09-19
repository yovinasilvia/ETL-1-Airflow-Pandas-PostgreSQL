from airflow import DAG
from datetime import datetime, timedelta

from airflow.operators.python import PythonOperator
from airflow.models import Variable
from airflow.hooks.postgres_hook import PostgresHook

import requests
import pandas as pd
from time import sleep

default_args = {
    'owner': 'yovina_silvia',
    'start_date': datetime(2023,1,1),
    'retries': 1,
    'retry_delta': timedelta(seconds=10)
}

def web_extract(**context):
    # Define Context
    ti = context['ti']
    
    # Define Scope Variable
    year = 2020
    seasons = ['winter','spring','summer','fall']

    # Define Initial Dataframe
    final_df = pd.DataFrame({
        'title': ['placeholder']
    })

    # Start Getting Data from API
    while year < 2024:
        for season in seasons:
            print(f'Anime of {year} {season}')
            for i in range(4):
                # Get data from target API
                url = (f'https://api.jikan.moe/v4/seasons/{year}/{season}?page={i+1}')
                result = requests.get(url)
                result_df = pd.json_normalize(result.json(), 'data')
                sleep(1)

                # Append the Dataframe to Final Dataframe
                final_df = pd.concat([final_df, result_df], axis=0, ignore_index=True)

                # Fill Null Seasons with the appropriate Season
                final_df['season'] = final_df['season'].fillna(season)

                # Fill Null Years with the appropriate Year
                final_df['year'] = final_df['year'].fillna(year)

        year = year + 1

    ti.xcom_push(key='animelist_df', value=final_df)

def data_transformation(**context):
    ti = context['ti']
    df = ti.xcom_pull(key='animelist_df', task_ids='extract_api_task')

    # Drop Unneeded Columns
    # Drop Unneeded Columns
    drop_list = ['mal_id', 'url', 'approved', 'titles', 'title_synonyms', 'status', 'airing', 'rating', 'scored_by', 
             'rank', 'popularity', 'favorites', 'synopsis', 'background', 'producers', 'licensors', 
             'explicit_genres', 'themes', 'demographics', 'images.jpg.image_url', 'images.jpg.small_image_url', 
             'images.jpg.large_image_url', 'images.webp.image_url', 'images.webp.small_image_url', 
             'images.webp.large_image_url', 'trailer.youtube_id', 'trailer.url', 'trailer.embed_url', 
             'trailer.images.image_url', 'trailer.images.small_image_url', 'trailer.images.medium_image_url', 
             'trailer.images.large_image_url', 'trailer.images.maximum_image_url', 'aired.from', 'aired.to', 
             'aired.prop.from.day', 'aired.prop.from.month', 'aired.prop.from.year', 'aired.string', 'aired.prop.to.day', 
             'aired.prop.to.month', 'aired.prop.to.year', 'broadcast.day', 'broadcast.time', 'broadcast.timezone', 
             'broadcast.string']
    df.drop(columns=drop_list, inplace=True)

    # Value Imputation on Null Columns (Using Median)
    df['episodes'] = df['episodes'].fillna(df['episodes'].median())
    df['score'] = df['score'].fillna(df['score'].median())

    # Drop Placeholder Row
    df.drop([0], axis=0, inplace=True)

    # Extract Genres and Studios
    df['genre_extracted'] = df['genres'].apply(lambda x: ", ".join([studio.get('name') for studio in x]))
    df['studio_extracted'] = df['studios'].apply(lambda x: ", ".join([studio.get('name') for studio in x]))

    # Drop Genres and Studios because Postgres cannot process numpy.ndarray
    df.drop(['genres', 'studios'], inplace=True, axis=1)

    # Return the filtered result
    ti.xcom_push(key='cleaned_animelist_df', value=df)

def load_into_postgres(**context):
    ti = context['ti']
    df = ti.xcom_pull(key='cleaned_animelist_df', task_ids='data_transformation_task')
    hook = PostgresHook(postgres_conn_id='postgres_db_conn')
    df.to_sql('jikan_animelist_2020-2023', hook.get_sqlalchemy_engine(), schema='transformed_data', if_exists='replace', chunksize=1000)

anime_project_dag = DAG(
    dag_id='animelist_dag',
    default_args=default_args,
    schedule_interval=None,
    catchup=False
)

extraction_task = PythonOperator(
    task_id='extract_api_task',
    python_callable=web_extract,
    provide_context=True,
    dag=anime_project_dag
)

transformation_task = PythonOperator(
    task_id='data_transformation_task',
    python_callable=data_transformation,
    provide_context=True,
    dag=anime_project_dag
)

load_data_task = PythonOperator(
    task_id='load_data_to_postgres_task',
    python_callable=load_into_postgres,
    provide_context=True,
    dag=anime_project_dag
)

extraction_task >> transformation_task >> load_data_task