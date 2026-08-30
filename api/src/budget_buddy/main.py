import datetime
import io
from functools import lru_cache
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile
from google import genai
from pydantic import BaseModel, Field

app = FastAPI()

@lru_cache
def get_client() -> genai.Client:
    return genai.Client()


class Transaction(BaseModel):
    date: datetime.date
    description: str
    amount: float


class ColumnMapping(BaseModel):
    skip_rows: int = Field(
        0, description="Number of rows to skip at the start of the CSV file."
    )
    delimiter: str = Field(",", description="Delimiter used in the CSV file.")
    date_column: str = Field(
        "date", description="Name of the column containing transaction dates."
    )
    date_format: str = Field(
        "%Y-%m-%d",
        description="Python strptime format string for parsing dates in the date column.",
    )
    description_column: str = Field(
        "description",
        description="Name of the column containing transaction descriptions.",
    )
    amount_column: str = Field(
        "amount", description="Name of the column containing transaction amounts."
    )
    amount_separator: Literal[".", ","] = Field(
        ".", description="Character used as the decimal separator in the amount column."
    )
    confidence: float = Field(
        0.8, description="Confidence that the date format is correct."
    )


def decode_csv(raw: bytes) -> tuple[str, str]:
    for enc in ["utf-8-sig", "cp1252", "latin-1"]:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode CSV file with available encodings.")


def infer_column_mapping(csv_text: str, client: genai.Client) -> ColumnMapping:
    head = "\n".join(csv_text.splitlines()[:10])
    prompt = "This is the start of a CSV file which contains bank transactions. Do not parse the transactions, determine the column mapping and return the mapping in JSON format. The first lines of the CSV file are:\n\n"
    interaction = client.interactions.create(
        model="gemini-flash-lite-latest",
        input=prompt + head,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": ColumnMapping.model_json_schema(),
        },
    )

    if not interaction.output_text:
        raise HTTPException(502, "Model returned no output")

    return ColumnMapping.model_validate_json(interaction.output_text)


def parse_transactions(csv_text: str, column_mapping: ColumnMapping) -> list[Transaction]:
    df = pd.read_csv(
        io.StringIO(csv_text),
        skiprows=column_mapping.skip_rows,
        delimiter=column_mapping.delimiter,
        parse_dates=[column_mapping.date_column],
        date_format=column_mapping.date_format,
        decimal=column_mapping.amount_separator,
        usecols=[
            column_mapping.date_column,
            column_mapping.amount_column,
            column_mapping.description_column,
        ],
    )

    df = df.where(pd.notna(df), None)
    df = df.rename(
        columns={
            column_mapping.date_column: "date",
            column_mapping.amount_column: "amount",
            column_mapping.description_column: "description",
        }
    )
    return [Transaction.model_validate(row) for row in df.to_dict(orient="records")]


@app.post("/transactions")
def csv_to_transactions(file: UploadFile) -> list[Transaction]:
    text, _ = decode_csv(file.file.read())

    client = get_client()
    column_mapping = infer_column_mapping(text, client)

    rows = parse_transactions(text, column_mapping)

    return rows
