from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import importlib
import inspect

app = FastAPI(title="Interview Config API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["http://localhost:5173"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Define schema (matches interview.py fields)
class InterviewInput(BaseModel):
    status: str | None = None
    itemizing: bool | None = None
    over_65: bool | None = None
    spouse_over_65: bool | None = None
    kids: int | None = None
    dependents: int | None = None
    s_loans: bool | None = None
    cap_gains: bool | None = None
    have_rr: bool | None = None
    self_emp: bool | None = None
    show_optional_zeros: bool | None = None
    debug: bool | None = None


# ✅ 1️⃣ GET /interview  → Fetch current interview values
@app.get("/interview")
def get_interview_values():
    try:
        interview = importlib.reload(importlib.import_module("interview"))
        # Extract public attributes (no __builtins__)
        data = {
            name: getattr(interview, name)
            for name, _ in inspect.getmembers(interview)
            if not name.startswith("__") and not inspect.ismodule(getattr(interview, name))
        }
        return {"interview_data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ✅ 2️⃣ POST /interview  → Update values in interview.py
@app.post("/interview")
def update_interview_values(update: InterviewInput):
    try:
        interview = importlib.import_module("interview")

        # Update attributes in the module dynamically
        for field, value in update.dict().items():
            if value is not None:
                setattr(interview, field, value)

        # Write back the updated values to interview.py
        with open("interview.py", "w") as f:
            f.write("# Auto-updated by API\n\n")
            for key, val in interview.__dict__.items():
                if not key.startswith("__") and not inspect.ismodule(val):
                    if isinstance(val, str):
                        f.write(f'{key}="{val}"\n')
                    else:
                        f.write(f"{key}={val}\n")

        return {"message": "interview.py updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # ✅ 1️⃣ GET /inform → Fetch all current inform.py variables
class InformInput(BaseModel):
    data: dict
@app.get("/inform")
def get_inform_values():
    try:
        inform = importlib.reload(importlib.import_module("inform"))
        data = {
            name: getattr(inform, name)
            for name, _ in inspect.getmembers(inform)
            if not name.startswith("__") and not inspect.ismodule(getattr(inform, name))
        }
        return {"inform_data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# ✅ 2️⃣ POST /inform → Update variables dynamically in inform.py
@app.post("/inform")
def update_inform_values(update: InformInput):
    try:
        inform = importlib.import_module("inform")

        # Update values from incoming dict
        for key, val in update.data.items():
            if hasattr(inform, key):
                setattr(inform, key, val)

        # Write updated values back to inform.py
        with open("inform.py", "w") as f:
            f.write("# Auto-updated by API\n\n")
            for key, val in inform.__dict__.items():
                if not key.startswith("__") and not inspect.ismodule(val):
                    f.write(f"{key} = {val}\n")

        return {"message": "inform.py updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    # ✅ 3️⃣ POST /calculate → Run tax computation and return results

# @app.post("/calculate")
# def calculate_tax():
#     try:
#         import io, contextlib, importlib, pathlib
#         taxes = importlib.import_module("taxes")
#         interview = importlib.reload(importlib.import_module("interview"))
#         inform = importlib.reload(importlib.import_module("inform"))

#         # ✅ Step 1: Load cells.py first (defines cell() and cell_list)
#         exec(open("cells.py").read(), globals())

#         # ✅ Step 2: Then load taxforms.py (which uses cell)
#         exec(open("taxforms.py").read(), globals())

#         # ✅ Step 3: Setup inform and compute
#         taxes.setup_inform(print_out=False)
#         taxes.cell_list["f1040_refund"].compute()
#         taxes.cell_list["f1040_tax_owed"].compute()
#         taxes.cell_list["f8582_carryover_to_next_year"].compute()

#         output = io.StringIO()
#         with contextlib.redirect_stdout(output):
#             taxes.print_a_form("Form 1040", "f1040")
#             taxes.print_a_form("Schedule 1", "f1040sch1")
#             taxes.print_a_form("Schedule 2", "f1040sch2")
#             taxes.print_a_form("Schedule 3", "f1040sch3")

#             if getattr(interview, "itemizing", False):
#                 taxes.print_a_form("Schedule A", "f1040_sched_a")

#             # Optional: charitable test
#             try:
#                 taxes.charitable()
#             except Exception as e:
#                 print("Charitable test skipped:", e)

#         printed_text = output.getvalue()

#         return {
#             "message": "Tax calculation completed successfully",
#             "refund": taxes.cell_list.get("f1040_refund").value if "f1040_refund" in taxes.cell_list else None,
#             "tax_owed": taxes.cell_list.get("f1040_tax_owed").value if "f1040_tax_owed" in taxes.cell_list else None,
#             "carryover": taxes.cell_list.get("f8582_carryover_to_next_year").value if "f8582_carryover_to_next_year" in taxes.cell_list else None,
#             "output_text": printed_text
#         }

#     except Exception as e:
#         import traceback
#         print("ERROR DETAILS:\n", traceback.format_exc())
#         raise HTTPException(status_code=500, detail=str(e))
@app.post("/calculate")
def calculate_tax():
    try:
        import io, contextlib, importlib

        taxes = importlib.import_module("taxes")
        interview = importlib.reload(importlib.import_module("interview"))
        inform = importlib.reload(importlib.import_module("inform"))

        # ✅ Step 1: Load cells.py (defines cell and cell_list)
        exec(open("cells.py").read(), globals())

        # ✅ Step 2: Load taxforms.py (depends on cell definitions)
        exec(open("taxforms.py").read(), globals())

        # ✅ Step 3: Run computations silently
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            taxes.setup_inform(print_out=False)
            taxes.cell_list["f1040_refund"].compute()
            taxes.cell_list["f1040_tax_owed"].compute()
            taxes.cell_list["f8582_carryover_to_next_year"].compute()

        # ✅ Step 4: Extract only needed final values
        refund = taxes.cell_list.get("f1040_refund").value if "f1040_refund" in taxes.cell_list else None
        tax_owed = taxes.cell_list.get("f1040_tax_owed").value if "f1040_tax_owed" in taxes.cell_list else None
        carryover = taxes.cell_list.get("f8582_carryover_to_next_year").value if "f8582_carryover_to_next_year" in taxes.cell_list else None

        # ✅ Step 5: Return only summarized results — no internal logs
        return {
            "message": "Tax calculation completed successfully ✅",
            "refund": round(refund or 0, 2),
            "tax_owed": round(tax_owed or 0, 2),
            "carryover_to_next_year": round(carryover or 0, 2)
        }

    except Exception as e:
        import traceback
        print("ERROR DETAILS:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
