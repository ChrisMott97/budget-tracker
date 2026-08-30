from fastapi import FastAPI, UploadFile
from fastapi.responses import RedirectResponse

app = FastAPI()

@app.get("/")
def read_root():
    response = RedirectResponse(url="/transactions")
    return response

@app.get("/transactions")
def reroute():
    return {"Error": "This is a POST endpoint. Please use POST method to parse transactions."}

@app.post("/transactions")
def parse_transactions(file: UploadFile):
    # take file as input

    # call AI to parse the transactions
    
    # return normalised transactions
    return {"filename": file.filename}
