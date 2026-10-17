import streamlit as st
import os
import json
from datetime import date
from pathlib import Path
import pandas as pd

from google import genai
from google.genai import types
from dotenv import load_dotenv

st.set_page_config(page_title="SpendIQ", layout="wide")

load_dotenv()

#Accessing the API key 
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("Set the GEMINI_API_KEY before running this script.")

client = genai.Client(api_key=api_key)


def show_model_error(action, error):
    if getattr(error, "code", None) == 500:
        st.error(f"{action} failed because Gemini returned an internal server error (500). Try again shortly.")
    else:
        st.error(f"{action} failed: {error}")

style_path = Path(__file__).with_name("style.css")
# Load presentation separately so UI changes don't clutter the app logic.
st.markdown(
    f"<style>{style_path.read_text(encoding='utf-8')}</style>",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="spendiq-header">
        <div class="spendiq-brand">
            <p class="spendiq-eyebrow">PERSONAL FINANCE</p>
            <div class="spendiq-wordmark">
                <div class="spendiq-monogram">S</div>
                <h1>SpendIQ</h1>
            </div>
        </div>
        <div class="spendiq-date">{date.today().strftime("%A, %d %B %Y")}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

#Loading the expenses.csv file and creating it if it doesn't exist
csv_path = Path(__file__).with_name("expenses.csv")
default_expenses = pd.DataFrame(
    {
        "Category": ["Allowance", "Food", "Entertainment", "Internet", "Transportation"],
        "Amount": [0, 0, 0, 0, 0],
        "Date": ["", "", "", "", ""],
    }
)

# Seed default categories only when no CSV data exists yet.
if not csv_path.exists() or csv_path.stat().st_size == 0:
    default_expenses.to_csv(csv_path, index=False)

try:
    df = pd.read_csv(csv_path)
except pd.errors.EmptyDataError:
    default_expenses.to_csv(csv_path, index=False)
    df = default_expenses

required_columns = {"Category", "Amount"}
if not required_columns.issubset(df.columns):
    st.error("expenses.csv must have 'Category' and 'Amount' columns.")
    st.stop()

# A header-only CSV has no categories to build inputs from.
if df.empty:
    df = default_expenses.copy()

# Treat blank amounts as zero, but reject nonblank values that aren't numeric.
blank_amounts = df["Amount"].isna() | df["Amount"].astype(str).str.strip().eq("")
numeric_amounts = pd.to_numeric(df["Amount"], errors="coerce")
if (numeric_amounts.isna() & ~blank_amounts).any():
    st.error("Every row in expenses.csv must have a numeric Amount.")
    st.stop()
df["Amount"] = numeric_amounts.fillna(0)
if df["Amount"].mod(1).ne(0).any():
    st.error("UGX amounts in expenses.csv must be whole numbers.")
    st.stop()
df["Amount"] = df["Amount"].astype(int)

df["Category"] = df["Category"].fillna("").astype(str).str.strip()
if df["Category"].eq("").any():
    st.error("Every row in expenses.csv must have a category.")
    st.stop()

# Older CSVs gain a Date column; their original dates remain unknown.
if "Date" not in df.columns:
    df["Date"] = ""
df["Date"] = df["Date"].fillna("").astype(str)
df.to_csv(csv_path, index=False)


def save_expense_entries():
    current_df = pd.read_csv(csv_path)
    entry_date = st.session_state["entry_date"].isoformat()
    new_rows = []

    allowance_amount = int(st.session_state.get("entry_allowance", 0))
    if allowance_amount > 0:
        new_rows.append(
            {"Category": "Allowance", "Amount": allowance_amount, "Date": entry_date}
        )

    for category in df["Category"].unique():
        if category.casefold() == "allowance":
            continue
        amount = int(st.session_state.get(f"entry_{category}", 0))
        if amount > 0:
            new_rows.append(
                {"Category": category, "Amount": amount, "Date": entry_date}
            )

    if not new_rows:
        st.session_state["expense_save_error"] = "Enter an amount greater than zero before saving."
        return

    # Append saved entries, then clear input state without clearing the CSV.
    updated_df = pd.concat([current_df, pd.DataFrame(new_rows)], ignore_index=True)
    updated_df.to_csv(csv_path, index=False)
    st.session_state["entry_allowance"] = 0
    for category in df["Category"].unique():
        if category.casefold() != "allowance":
            st.session_state[f"entry_{category}"] = 0
    st.session_state["expense_save_success"] = True


def save_receipt_items(receipt_rows):
    if not isinstance(receipt_rows, pd.DataFrame) or receipt_rows.empty:
        st.session_state["receipt_save_error"] = "Add at least one receipt item before saving."
        return

    receipt_rows = receipt_rows[["Category", "Amount"]].copy()
    receipt_rows["Category"] = receipt_rows["Category"].fillna("").astype(str).str.strip()
    receipt_rows["Amount"] = pd.to_numeric(receipt_rows["Amount"], errors="coerce")
    if receipt_rows["Category"].eq("").any():
        st.session_state["receipt_save_error"] = "Each receipt item needs a category."
        return
    if receipt_rows["Amount"].isna().any() or (receipt_rows["Amount"] < 0).any():
        st.session_state["receipt_save_error"] = "Receipt amounts must be nonnegative numbers."
        return
    if receipt_rows["Amount"].mod(1).ne(0).any():
        st.session_state["receipt_save_error"] = "UGX receipt amounts must be whole numbers."
        return
    if receipt_rows["Category"].str.casefold().eq("allowance").any():
        st.session_state["receipt_save_error"] = "Receipt items must use an expense category, not Allowance."
        return

    # Match extracted categories case-insensitively while preserving CSV spelling.
    current_df = pd.read_csv(csv_path)
    category_names = {category.casefold(): category for category in current_df["Category"]}
    receipt_rows["Category"] = receipt_rows["Category"].map(
        lambda category: category_names.get(category.casefold(), category)
    )
    receipt_rows["Amount"] = receipt_rows["Amount"].astype(int)
    receipt_rows["Date"] = st.session_state["entry_date"].isoformat()
    updated_df = pd.concat([current_df, receipt_rows], ignore_index=True)
    updated_df.to_csv(csv_path, index=False)

    st.session_state.pop("receipt_items", None)
    st.session_state["receipt_save_success"] = True
    st.rerun()


with st.expander("Manage categories"):
    with st.form("add_category_form", clear_on_submit=True):
        new_category = st.text_input("Add a spending category")
        add_category = st.form_submit_button("Add category")

    if add_category:
        normalized_category = new_category.strip()
        if not normalized_category:
            st.warning("Enter a category name first.")
        elif normalized_category.casefold() in df["Category"].str.casefold().values:
            st.warning("That category already exists.")
        else:
            df = pd.concat(
                [df, pd.DataFrame([{"Category": normalized_category, "Amount": 0, "Date": ""}])],
                ignore_index=True,
            )
            df.to_csv(csv_path, index=False)
            st.rerun()

    removable_categories = [
        category for category in df["Category"] if category.casefold() != "allowance"
    ]
    if removable_categories:
        with st.form("remove_category_form"):
            category_to_remove = st.selectbox("Category to remove", removable_categories)
            confirm_removal = st.checkbox(
                f"Permanently delete {category_to_remove} and its saved amount"
            )
            remove_category = st.form_submit_button("Remove category")

        if remove_category:
            if not confirm_removal:
                st.warning("Confirm the deletion before removing this category.")
            else:
                df = df[df["Category"] != category_to_remove]
                df.to_csv(csv_path, index=False)
                st.session_state.pop(f"entry_{category_to_remove}", None)
                st.rerun()
expense_categories = [
    category for category in df["Category"].unique() if category.casefold() != "allowance"
]

st.subheader("Log your expenditure for the selected day")
with st.container(border=True):
    date_column, allowance_column = st.columns(2)
    with date_column:
        entry_date = st.date_input("Entry date", value=date.today(), key="entry_date")
    with allowance_column:
        allowance_entry = st.number_input(
            "Allowance received (UGX)", min_value=0, value=0, step=1, key="entry_allowance"
        )

category_values = {}
with st.container(border=True):
    st.markdown("#### Spending categories")
    input_columns = st.columns(2)
    for index, category in enumerate(expense_categories):
        with input_columns[index % len(input_columns)]:
            category_values[category] = st.number_input(
                f"{category} (UGX)",
                min_value=0,
                value=0,
                step=1,
                key=f"entry_{category}",
            )
    goal = st.number_input(
        "Savings goal (UGX)", min_value=0, value=0, step=1, key="savings_goal"
    )

save_column, download_column = st.columns([1, 1])
with save_column:
    st.button("Save entries", on_click=save_expense_entries, use_container_width=True)
with download_column:
    st.download_button(
        "Download CSV",
        data=csv_path.read_bytes(),
        file_name="expenses.csv",
        mime="text/csv",
        use_container_width=True,
    )

expense_save_error = st.session_state.pop("expense_save_error", None)
if expense_save_error:
    st.error(expense_save_error)
if st.session_state.pop("expense_save_success", False):
    st.success("Entries saved to expenses.csv.")

uploaded_receipt = st.file_uploader(
    "Upload a receipt (optional)", type=["jpg", "jpeg", "jfif", "png", "pdf"]
)
if uploaded_receipt and st.button("Extract receipt items"):
    mime_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".jfif": "image/jpeg",
        ".png": "image/png",
        ".pdf": "application/pdf",
    }[Path(uploaded_receipt.name).suffix.lower()]
    receipt_part = types.Part.from_bytes(
        data=uploaded_receipt.getvalue(),
        mime_type=mime_type,
    )
    prompt = (
        "Extract purchased items and their amounts from this receipt. Return only valid JSON in this format: "
        '{"items":[{"description":"...","category":"...","amount":0}]}. '
        "Use nonnegative whole-number UGX amounts, do not invent amounts, and use one of these categories or Other: "
        + ", ".join(expense_categories + ["Other"])
    )
    try:
        response = client.models.generate_content(
            model="gemma-4-26b-a4b-it",
            contents=[prompt, receipt_part],
        )
        # Models may wrap otherwise-valid JSON in a Markdown code fence.
        response_text = (response.text or "").strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[-1].removesuffix("```").strip()
        extracted = json.loads(response_text).get("items", [])
        valid_items = []
        for item in extracted:
            amount = pd.to_numeric(item.get("amount"), errors="coerce")
            category = str(item.get("category", "")).strip()
            if category and pd.notna(amount) and amount >= 0 and float(amount).is_integer():
                valid_items.append(
                    {
                        "Description": str(item.get("description", "")),
                        "Category": category,
                        "Amount": int(amount),
                    }
                )
        if not valid_items:
            st.warning("No valid item amounts were found. Check the receipt or enter the expense manually.")
        else:
            st.session_state["receipt_items"] = pd.DataFrame(valid_items)
    except Exception as error:
        show_model_error("Receipt extraction", error)

if "receipt_items" in st.session_state:
    st.write("Review or edit the extracted values before saving them.")
    edited_receipt_items = st.data_editor(
        st.session_state["receipt_items"],
        num_rows="dynamic",
        column_config={
            "Amount": st.column_config.NumberColumn(
                "Amount",
                min_value=0,
                step=1,
                format="%d",
            )
        },
        key="receipt_items_editor",
    )
    if st.button("Add receipt items to CSV"):
        save_receipt_items(edited_receipt_items)

receipt_save_error = st.session_state.pop("receipt_save_error", None)
if receipt_save_error:
    st.error(receipt_save_error)
if st.session_state.pop("receipt_save_success", False):
    st.success("Receipt amounts added to their categories in expenses.csv.")

selected_month = pd.Period(entry_date, freq="M")
# Undated legacy rows stay in the CSV but cannot be assigned to a monthly total.
row_months = pd.to_datetime(df["Date"], errors="coerce").dt.to_period("M")
month_df = df.loc[row_months == selected_month]
saved_allowance_values = month_df.loc[
    month_df["Category"].str.casefold() == "allowance", "Amount"
]
allowance = int(saved_allowance_values.sum()) + allowance_entry
saved_expenses = month_df[month_df["Category"].str.casefold() != "allowance"]
saved_totals = saved_expenses.groupby("Category")["Amount"].sum().to_dict()
combined_totals = dict(saved_totals)
for category, amount in category_values.items():
    combined_totals[category] = combined_totals.get(category, 0) + amount
total_expenses = sum(combined_totals.values())
balance = allowance - total_expenses
expense_summary = "\n".join(
    f"- {category}: UGX {amount}" for category, amount in combined_totals.items()
)
st.subheader(entry_date.strftime("%B %Y"))
allowance_metric, expenses_metric, balance_metric, savings_metric = st.columns(4)
allowance_metric.metric("Allowance", f"UGX {allowance:,.0f}")
expenses_metric.metric("Spent", f"UGX {total_expenses:,.0f}")
balance_metric.metric("Remaining", f"UGX {balance:,.0f}")
savings_metric.metric("Savings goal", f"UGX {goal:,.0f}")
if df["Date"].eq("").any():
    st.caption("Older rows without a recorded date remain in the CSV but aren't included in monthly totals.")

st.subheader("Monthly insight")
if st.button("Analyze my month", type="primary"):
    prompt = f"""
    You are SpendIQ, a financial advisor for university students.

    Monthly allowance: UGX {allowance}

    Expenses:
    {expense_summary}

    Total expenses: UGX {total_expenses}
    Remaining balance: UGX {balance}
    Savings goal: UGX {goal}

    Provide:

    1. Spending Analysis
    2. Financial Risks
    3. Areas of Overspending
    4. Budget Recommendations
    5. Savings Advice
    6. Estimate how long it may take the student to reach their savings goal.

    Be specific and practical.
    Use bullet points.
    Keep the response under 250 words.
    """

    try:
        response = client.models.generate_content(
            model="gemma-4-26b-a4b-it", contents=prompt)
        st.subheader("Analysis Result")
        st.write(response.text)
    except Exception as error:
        show_model_error("Budget analysis", error)

st.subheader("Ask SpendIQ")
with st.form("budget_question_form"):
    question = st.text_input("Your question")
    get_answer = st.form_submit_button("Get answer")

if get_answer:
    if question.strip():
        prompt = f"""
        You are SpendIQ, a financial advisor for university students.

        Monthly allowance: UGX {allowance}

        Expenses:
        {expense_summary}

        Total expenses: UGX {total_expenses}
        Remaining balance: UGX {balance}
        Savings goal: UGX {goal}

        Student's question: "{question}"

        Provide a clear and concise answer to the student's question based on their budget.
        """
        
        try:
            response = client.models.generate_content(
                model="gemma-4-26b-a4b-it", contents=prompt)
            st.subheader("Answer")
            st.write(response.text)
        except Exception as error:
            show_model_error("Budget question", error)
    
