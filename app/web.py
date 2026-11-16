from fastapi import APIRouter,Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.config import MODULES,TITLE,RULE_VERSION
from app.modules.m7_batches.service import run
from app.modules.m8_period import service as period_service
from app.store import fetch
router=APIRouter();templates=Jinja2Templates(directory="app/templates")
@router.get("/")
def home():return RedirectResponse("/model")
def page(request,slug,run_id):
    data=fetch(run_id) if run_id else run({"sample":"dirty"})
    return templates.TemplateResponse(request=request,name=slug+".html",context={"data":data,"title":TITLE,"modules":MODULES,"slug":slug,"page_title":dict(MODULES)[slug],"version":RULE_VERSION})
def periods_page(request:Request,supplement_id:str|None=None):
    base=run({"sample":"dirty"})
    context={"data":base,"period":period_service.state(supplement_id),"title":TITLE,"modules":MODULES,"slug":"periods","page_title":dict(MODULES)["periods"],"version":RULE_VERSION}
    return templates.TemplateResponse(request=request,name="periods.html",context=context)
for slug,label in MODULES:
    if slug=="periods":
        router.add_api_route("/periods",periods_page,methods=["GET"],include_in_schema=False)
        continue
    def view(request:Request,run_id:str|None=None,_slug=slug):return page(request,_slug,run_id)
    router.add_api_route("/"+slug,view,methods=["GET"],include_in_schema=False)
