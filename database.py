import os

import mysql.connector
from dotenv import load_dotenv


load_dotenv()


def get_db_connection():
    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        connection_timeout=5,
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE")
    )

    return connection
if __name__ == "__main__":

    connection = get_db_connection()

    print("MySQL 连接成功")

    connection.close()