from fastapi import APIRouter
from app.errors import DomainError,http_error
from . import service
router=APIRouter()

@router.get("/api/periods")
def get_state():
    try:return service.state()
    except DomainError as exc:raise http_error(exc)

@router.post("/api/periods/close")
def close(options:dict):
    try:return service.close_period(options)
    except DomainError as exc:raise http_error(exc)

@router.post("/api/periods/supplements")
def supplement(options:dict):
    try:return service.submit_supplement(options)
    except DomainError as exc:raise http_error(exc)

@router.get("/api/periods/supplements/{supplement_id}")
def get_supplement(supplement_id:str):
    try:return service.state(supplement_id)
    except DomainError as exc:raise http_error(exc)

@router.post("/api/periods/supplements/{supplement_id}/review")
def review_supplement(supplement_id:str,options:dict):
    try:
        from app.store import review_supplement as do_review
        return do_review(supplement_id,options.get("revision"),options.get("decision"))
    except DomainError as exc:raise http_error(exc)
