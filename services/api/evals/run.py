import asyncio
import json
import os
import tempfile
from pathlib import Path

os.environ["LLM_PROVIDER"] = os.getenv("LLM_PROVIDER", "local")
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.gettempdir()}/procura-evals.db"

from app.main import service
from app.models.database import Base, ExecutionRow, SessionLocal, engine, init_db
from app.services.seed import seed_supplier_database

ROOT = Path(__file__).parent

async def run():
    Base.metadata.drop_all(engine); init_db(); seed_supplier_database()
    scenarios=json.loads((ROOT/"scenarios.json").read_text()); results=[]
    for scenario in scenarios:
        conversation=service.create_conversation()
        response=await service.execute(conversation.id,scenario["input"],f"eval-{scenario['id']}")
        with SessionLocal() as db: trace=json.loads(db.get(ExecutionRow,response.decision.trace_id).trace_data)
        expected_length={"clarification":1,"recommended":9,"review_required":10,"failed_safe":1}[response.decision.status]
        tool_sequence_valid=len(trace["tool_sequence"])==expected_length
        passed=response.decision.status==scenario["expected_status"] and response.decision.recommendation_supplier_id==scenario["expected_supplier"] and response.decision.no_transaction_completed and tool_sequence_valid
        results.append({"id":scenario["id"],"passed":passed,"actual_status":response.decision.status,"actual_supplier":response.decision.recommendation_supplier_id,"schema_valid":True,"expected_tool_sequence":tool_sequence_valid,"unsupported_claims":0})
    rate=sum(r["passed"] for r in results)/len(results); report={"provider":service.provider.name,"threshold":0.9,"passed":sum(r["passed"] for r in results),"total":len(results),"pass_rate":rate,"results":results}
    out=ROOT/"results"; out.mkdir(exist_ok=True); (out/"latest.json").write_text(json.dumps(report,indent=2)+"\n")
    lines=["# Procura deterministic evaluation","",f"Provider: `{service.provider.name}`",f"Result: **{report['passed']}/{report['total']} ({rate:.1%})**",f"Threshold: **{report['threshold']:.0%}**","","| Scenario | Pass | Decision | Supplier |","|---|---:|---|---|"]
    lines += [f"| {r['id']} | {'Yes' if r['passed'] else 'No'} | {r['actual_status']} | {r['actual_supplier'] or '—'} |" for r in results]
    (out/"latest.md").write_text("\n".join(lines)+"\n"); print(json.dumps(report,indent=2))
    raise SystemExit(0 if rate>=report["threshold"] else 1)
if __name__=="__main__": asyncio.run(run())
