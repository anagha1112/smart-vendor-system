import streamlit as st
import pandas as pd
import os
import googlemaps
from datetime import datetime, time
import csv
import polyline # Required for decoding Google Maps route polylines
import numpy as np

# --- Page Configuration ---
st.set_page_config(page_title="Smart Vendor Management System", layout="wide")

# --- Pydeck Import (for Maps) ---
try:
    import pydeck as pdk
except ImportError:
    st.error("Please install pydeck and polyline: pip install pydeck polyline")
    pdk = None

# --- Google Maps Client Initialization ---
try:
    gmaps = googlemaps.Client(key=st.secrets["GOOGLE_MAPS_API_KEY"])
except (FileNotFoundError, KeyError):
    gmaps = None

# --- File Paths ---
USERS_FILE = "users.csv"
VENDORS_FILE = "vendor_data.csv"
NOTIFICATIONS_FILE = "notifications.csv"
REQUIREMENTS_FILE = "requirements.csv" 
REVIEWS_FILE = "reviews.csv"
CERTIFICATES_FILE = "certificates.csv"
VENDOR_PROFILES_FILE = "vendor_profiles.csv" # New file for company profile info

# --- Global Data Definitions ---
BRAND_OPTIONS = {
    "Cement": ["Ultratech", "Ambuja", "ACC", "Other"],
    "Steel": ["TATA", "JSW", "SAIL", "Other"],
    "Electrical": ["Finolex", "Havells", "Polycab", "Other"],
    "Plumbing": ["Supreme", "Ashirvad", "Astral", "Other"],
    "Wood": ["Greenply", "CenturyPly", "Other"]
}
MEASUREMENT_OPTIONS = {
    "Cement": ["OPC 43", "OPC 53", "PPC", "Other"],
    "Steel": ["8mm", "10mm", "12mm", "16mm", "Other"]
}
QUANTITY_UNITS = {
    "Cement": "Bags",
    "Steel": "Tonnes",
    "Electrical": "Pieces",
    "Plumbing": "Pieces",
    "Wood": "Cubic Feet"
}
QUALITY_LEVELS = ["Premium", "Standard", "Basic"]
OWNERSHIP_TYPES = ["Private", "Government", "Cooperative"]
MATERIAL_CERTIFICATIONS = {
    "Cement": ["BIS/ISI Certificate", "MTC (Batch-wise)", "ISO Certification of Manufacturer", "Product Specification Sheet"],
    "Steel": ["BIS/ISI Certificate", "MTC with Heat Number", "ISO Certificate (of manufacturer)", "Brand Authorization Letter"],
    "Wood": ["IS Compliance Certificate", "FSC / PEFC Certificate", "Treatment Certificate", "Moisture Content Report"]
}
PROCUREMENT_EMAIL = "procurement@company.com"


# --- Data Initialization ---
PREDEFINED_USERS = [
    ["procure_user", "proc123", "Procurement"],
    ["site_user", "site123", "Site"]
]

VENDOR_COLUMNS = [
    "submitted_by", "company", "category", "brand", "item", "measurement",
    "quantity", "quantity_unit", "rate", "phone", "address", "status",
    "offered_quality", "offered_certifications", 
    "delivery_boy_name", "delivery_boy_phone", "scheduled_delivery_datetime"
]
REVIEW_COLUMNS = ["proposal_index", "rating", "review", "reviewed_by", "timestamp"]
REQUIREMENT_COLUMNS = ["item_category", "item_name", "budgeted_rate", "budgeted_quantity", "budgeted_quantity_unit", "required_quality", "required_certifications", "required_delivery_date"]
CERTIFICATE_COLUMNS = ["proposal_index", "certification_type", "certificate_details", "submitted_on"]
VENDOR_PROFILE_COLUMNS = ["vendor_username", "year_of_establishment", "ownership_type"]


# --- File Creation ---
def initialize_csv(file_path, columns):
    if not os.path.exists(file_path):
        with open(file_path, "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(columns)

initialize_csv(VENDORS_FILE, VENDOR_COLUMNS)
initialize_csv(NOTIFICATIONS_FILE, ["username", "message", "timestamp", "is_read"])
initialize_csv(REQUIREMENTS_FILE, REQUIREMENT_COLUMNS)
initialize_csv(REVIEWS_FILE, REVIEW_COLUMNS)
initialize_csv(CERTIFICATES_FILE, CERTIFICATE_COLUMNS)
initialize_csv(VENDOR_PROFILES_FILE, VENDOR_PROFILE_COLUMNS)


if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["username", "password", "role"])
        for user in PREDEFINED_USERS:
            writer.writerow(user)

# --- Session State Initialization ---
st.session_state.setdefault("logged_in", False)
st.session_state.setdefault("username", "")
st.session_state.setdefault("role", "")
st.session_state.setdefault("page", "Login")
st.session_state.setdefault("analysis_results", None)
st.session_state.setdefault("analyzed_category", None)
st.session_state.setdefault("edit_req_idx", None)
st.session_state.setdefault("edit_proposal_idx", None)


# --- Helper Functions ---
def load_and_validate_df(file_path, columns):
    try:
        dtype_spec = {'phone': str, 'delivery_boy_phone': str}
        df = pd.read_csv(file_path, dtype=dtype_spec)
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        return df
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=columns)

def get_vendor_ratings():
    try:
        reviews_df = pd.read_csv(REVIEWS_FILE)
        vendors_df = pd.read_csv(VENDORS_FILE)
        merged_df = pd.merge(reviews_df, vendors_df.reset_index().rename(columns={'index': 'proposal_index'}), on='proposal_index')
        return merged_df.groupby('submitted_by')['rating'].mean().to_dict()
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return {}

def switch_page(page_name):
    st.session_state.page = page_name
    st.rerun()

def add_notification(username, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if username in ["ALL_PROCUREMENT", "ALL_SITE"]:
        try:
            users_df = pd.read_csv(USERS_FILE)
            target_role = "Procurement" if username == "ALL_PROCUREMENT" else "Site"
            target_users = users_df[users_df['role'] == target_role]['username'].tolist()
            with open(NOTIFICATIONS_FILE, "a", newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                for user in target_users:
                    writer.writerow([user, message, timestamp, "False"])
        except (FileNotFoundError, pd.errors.EmptyDataError): pass
    else:
        with open(NOTIFICATIONS_FILE, "a", newline='', encoding='utf-8') as f:
            csv.writer(f).writerow([username, message, timestamp, "False"])

def get_notifications(username):
    try:
        notifications_df = pd.read_csv(NOTIFICATIONS_FILE)
        user_notifications = notifications_df[(notifications_df['username'] == username) & (notifications_df['is_read'] == False)].copy()
        user_notifications['timestamp'] = pd.to_datetime(user_notifications['timestamp'])
        return user_notifications.sort_values(by='timestamp', ascending=False)
    except (FileNotFoundError, pd.errors.EmptyDataError, KeyError):
        return pd.DataFrame()

def mark_notifications_as_read(username):
    try:
        notifications_df = pd.read_csv(NOTIFICATIONS_FILE)
        notifications_df.loc[notifications_df['username'] == username, 'is_read'] = True
        notifications_df.to_csv(NOTIFICATIONS_FILE, index=False)
    except (FileNotFoundError, pd.errors.EmptyDataError): pass

def get_distance(origin, destination):
    if not gmaps: return "API Key not configured", 0
    try:
        res = gmaps.directions(origin, destination, mode="driving")
        if res: return res[0]['legs'][0]['distance']['text'], res[0]['legs'][0]['distance']['value']
        return "No route found", 0
    except Exception: return "Error calculating", 0

# --- UI Components ---
def display_notifications():
    with st.sidebar:
        notifications = get_notifications(st.session_state.username)
        with st.expander(f"🔔 Notifications ({len(notifications)})", expanded=False):
            if not notifications.empty:
                for _, row in notifications.iterrows():
                    st.info(f"{row['message']} \n_{row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}_")
                if st.button("Mark all as read"):
                    mark_notifications_as_read(st.session_state.username)
                    st.rerun()
            else:
                st.write("No new notifications.")

# --- Auth Pages ---
def signup_page():
    st.title("📝 Vendor Registration")
    st.info("Please provide your company details to create an account.")
    with st.form("signup_form"):
        new_username = st.text_input("Choose a Username")
        year_of_establishment = st.number_input("Year of Establishment", min_value=1900, max_value=datetime.now().year, step=1)
        ownership_type = st.selectbox("Ownership Type", OWNERSHIP_TYPES)

        if st.form_submit_button("Register as Vendor"):
            if new_username and year_of_establishment and ownership_type:
                try:
                    users_df = pd.read_csv(USERS_FILE)
                    if not users_df[(users_df['username'] == new_username) & (users_df['role'] == "Vendor")].empty:
                        st.error("Username already taken.")
                    else:
                        with open(USERS_FILE, "a", newline='', encoding='utf-8') as f:
                            csv.writer(f).writerow([new_username, "N/A", "Vendor"])
                        
                        with open(VENDOR_PROFILES_FILE, "a", newline='', encoding='utf-8') as f:
                            csv.writer(f).writerow([new_username, year_of_establishment, ownership_type])

                        add_notification("ALL_PROCUREMENT", f"New vendor '{new_username}' has registered.")
                        st.success("Account created! Please log in.")
                        switch_page("Login")
                except (FileNotFoundError, pd.errors.EmptyDataError):
                    # Handle case where files don't exist
                    with open(USERS_FILE, "w", newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(["username", "password", "role"])
                        writer.writerow([new_username, "N/A", "Vendor"])
                    
                    with open(VENDOR_PROFILES_FILE, "w", newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(VENDOR_PROFILE_COLUMNS)
                        writer.writerow([new_username, year_of_establishment, ownership_type])

                    add_notification("ALL_PROCUREMENT", f"New vendor '{new_username}' has registered.")
                    st.success("Account created! Please log in.")
                    switch_page("Login")
            else:
                st.warning("Please fill in all fields.")
    if st.button("Already have an account? Login"):
        switch_page("Login")

def login_page():
    st.title("🔐 Login")
    role = st.selectbox("Select Your Role", ["Vendor", "Procurement", "Site"])
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password") if role != "Vendor" else None
        if st.form_submit_button("Login"):
            try:
                users_df = pd.read_csv(USERS_FILE)
                user_data = users_df[(users_df['username'] == username) & (users_df['role'] == role)]
                if not user_data.empty:
                    auth = (role == "Vendor") or (user_data.iloc[0]['password'] == password)
                    if auth:
                        st.session_state.update(logged_in=True, username=username, role=role)
                        st.success("Logged in successfully!")
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")
                else:
                    st.error("Invalid credentials.")
            except (FileNotFoundError, pd.errors.EmptyDataError):
                st.error("No users found.")
    if st.button("New Vendor? Register Here"):
        switch_page("Sign Up")

# --- Dashboards ---
def vendor_dashboard():
    st.title(f"📤 Welcome, {st.session_state.username} (Vendor Portal)")

    df = load_and_validate_df(VENDORS_FILE, VENDOR_COLUMNS)
    my_proposals = df[df['submitted_by'] == st.session_state.username].copy()
    my_proposal_indices = my_proposals.index.tolist()

    try:
        reviews_df = pd.read_csv(REVIEWS_FILE)
        my_reviews = reviews_df[reviews_df['proposal_index'].isin(my_proposal_indices)]
        if not my_reviews.empty:
            average_rating = my_reviews['rating'].mean()
            st.metric(label="⭐ Your Average Rating", value=f"{average_rating:.2f} / 5")
        else:
            st.metric(label="⭐ Your Average Rating", value="No reviews yet")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        st.metric(label="⭐ Your Average Rating", value="No reviews yet")

    st.markdown("---")

    action_required_count = len(my_proposals[my_proposals['status'] == 'Awaiting Certificates'])
    accepted_count = len(my_proposals[my_proposals['status'] == 'Accepted'])
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Submit Proposal", "Pending", f"Action Required ({action_required_count})", f"Accepted ({accepted_count})", "History"])

    with tab1:
        st.selectbox("1. Select Item Category", list(BRAND_OPTIONS.keys()) + ["Other"], key="vendor_category_selector")
        with st.form("vendor_form", clear_on_submit=True):
            category = st.session_state.vendor_category_selector
            st.write("2. Fill proposal details")
            company = st.text_input("Company Name")
            brand = st.selectbox(f"Brand for {category}", BRAND_OPTIONS.get(category, ["Other"]))
            if brand == "Other": brand = st.text_input("Specify Brand")
            item = st.text_input("Item Name (e.g., 'TMT Rods')")
            measurement = st.selectbox(f"Specification for {category}", MEASUREMENT_OPTIONS.get(category, ["Other"])) if category in MEASUREMENT_OPTIONS else st.text_input(f"Specification for {category}")
            if measurement == "Other": measurement = st.text_input("Specify Measurement")
            
            offered_quality = st.selectbox("Quality Level", QUALITY_LEVELS)
            offered_certs = st.multiselect("Available Material Certifications", MATERIAL_CERTIFICATIONS.get(category, []))

            address = st.text_input("Full Address")
            quantity_unit = QUANTITY_UNITS.get(category, "")
            if not quantity_unit:
                quantity_unit = st.text_input("Specify Unit (e.g., Litres)")
            quantity = st.number_input(f"Quantity (in {quantity_unit or 'Units'})", 1)
            rate = st.number_input("Rate (per unit)", 0.01, format="%.2f")
            phone = st.text_input("Phone Number", max_chars=10)

            if st.form_submit_button("Submit Proposal"):
                is_valid = phone.isdigit() and len(phone) == 10 and all([company, category, item, address, quantity, rate, phone, brand, measurement, quantity_unit])
                if is_valid:
                    new_proposal = {
                        "submitted_by": st.session_state.username, "company": company, "category": category,
                        "brand": brand, "item": item, "measurement": measurement, "quantity": quantity,
                        "quantity_unit": quantity_unit, "rate": rate, "phone": phone, "address": address, 
                        "status": "Pending", "offered_quality": offered_quality, "offered_certifications": ", ".join(offered_certs),
                        "delivery_boy_name": "", "delivery_boy_phone": "", "scheduled_delivery_datetime": ""
                    }
                    pd.DataFrame([new_proposal]).to_csv(VENDORS_FILE, mode='a', header=not os.path.exists(VENDORS_FILE), index=False)
                    add_notification("ALL_PROCUREMENT", f"New proposal from {company}.")
                    st.success("✅ Proposal submitted!")
                    st.rerun()
                else:
                    st.warning("Please fill all fields and enter a valid 10-digit phone number.")

    with tab2:
        st.header("⏳ Your Pending Proposals")
        pending = my_proposals[my_proposals['status'] == 'Pending']
        if pending.empty:
            st.info("No pending proposals.")
        else:
            for index, row in pending.iterrows():
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.write(f"**Item:** {row['item']} ({row['measurement']}) | **Brand:** {row['brand']} | **Status:** {row['status']}")
                with col2:
                    if st.button("Edit", key=f"edit_{index}"):
                        st.session_state.edit_proposal_idx = index
                        st.rerun()
        
        if st.session_state.edit_proposal_idx is not None:
            edit_index = st.session_state.edit_proposal_idx
            proposal_to_edit = my_proposals.loc[edit_index]
            with st.form("edit_proposal_form"):
                st.warning(f"Editing proposal for: **{proposal_to_edit['item']}**")
                
                company = st.text_input("Company Name", value=proposal_to_edit['company'])
                brand = st.text_input("Brand", value=proposal_to_edit['brand'])
                item = st.text_input("Item Name", value=proposal_to_edit['item'])
                measurement = st.text_input("Measurement", value=proposal_to_edit['measurement'])
                quantity = st.number_input("Quantity", value=int(proposal_to_edit['quantity']))
                rate = st.number_input("Rate", value=float(proposal_to_edit['rate']))
                phone = st.text_input("Phone Number", value=proposal_to_edit['phone'], max_chars=10)
                address = st.text_input("Address", value=proposal_to_edit['address'])

                save_col, cancel_col = st.columns(2)
                if save_col.form_submit_button("Save Changes"):
                    if phone.isdigit() and len(phone) == 10:
                        df.loc[edit_index, ['company', 'brand', 'item', 'measurement', 'quantity', 'rate', 'phone', 'address']] = [company, brand, item, measurement, quantity, rate, phone, address]
                        df.to_csv(VENDORS_FILE, index=False)
                        st.session_state.edit_proposal_idx = None
                        st.success("Proposal updated!")
                        st.rerun()
                    else:
                        st.error("Please enter a valid 10-digit phone number.")

                if cancel_col.form_submit_button("Cancel"):
                    st.session_state.edit_proposal_idx = None
                    st.rerun()


    with tab3:
        st.header("Action Required: Email Certificates")
        action_required = my_proposals[my_proposals['status'] == 'Awaiting Certificates']
        if action_required.empty:
            st.info("No proposals are currently awaiting certificate submission.")
        else:
            for index, row in action_required.iterrows():
                with st.container(border=True):
                    st.warning(f"Action Required for: **{row['item']}**")
                    st.write(f"Your proposal has been provisionally accepted. Please email your material certificates to **{PROCUREMENT_EMAIL}** for final verification.")
                    if st.button("I Have Emailed the Certificates", key=f"emailed_certs_{index}"):
                        df.loc[index, "status"] = "Certificates Submitted"
                        df.to_csv(VENDORS_FILE, index=False)
                        add_notification("ALL_PROCUREMENT", f"Certificates have been submitted via email for '{row['item']}' from {row['company']}.")
                        st.success("Confirmation sent to procurement team.")
                        st.rerun()

    with tab4:
        st.header("✅ Accepted Proposals (Ready to Dispatch)")
        accepted = my_proposals[my_proposals['status'] == 'Accepted']
        if accepted.empty:
            st.info("No proposals are currently accepted and waiting for dispatch.")
        else:
            for index, row in accepted.iterrows():
                with st.container(border=True):
                    st.write(f"**Item:** {row['item']} ({row['measurement']}) | **Brand:** {row['brand']}")
                    with st.form(f"dispatch_{index}", clear_on_submit=True):
                        st.info("Accepted! Schedule the delivery.")
                        name = st.text_input("Delivery Person Name")
                        phone = st.text_input("Delivery Person Phone", max_chars=10)
                        date = st.date_input("Delivery Date")
                        time_val = st.time_input("Delivery Time", time(9, 0))
                        if st.form_submit_button("Dispatch Item"):
                            if name and phone.isdigit() and len(phone) == 10:
                                dt = datetime.combine(date, time_val)
                                df.loc[index, ["status", "delivery_boy_name", "delivery_boy_phone", "scheduled_delivery_datetime"]] = ["Out for Delivery", name, phone, dt.strftime("%Y-%m-%d %H:%M:%S")]
                                df.to_csv(VENDORS_FILE, index=False)
                                add_notification("ALL_PROCUREMENT", f"DISPATCHED: '{row['item']}' from {row['company']}.")
                                add_notification("ALL_SITE", f"DELIVERY: '{row['item']}' from {row['company']} scheduled for {dt.strftime('%Y-%m-%d %H:%M')}.")
                                st.success("Dispatched!")
                                st.rerun()
                            else:
                                st.warning("Enter valid details for delivery person.")
    
    with tab5:
        st.header("📖 Your Proposal History")
        history = my_proposals[my_proposals['status'].isin(['Rejected', 'Out for Delivery', 'Delivered', 'Reviewed'])]
        if history.empty:
            st.info("No proposal history.")
        else:
            for index, row in history.iterrows():
                with st.container(border=True):
                    st.write(f"**Item:** {row['item']} ({row['measurement']}) | **Brand:** {row['brand']} | **Status:** {row['status']}")
                    if row['status'] == 'Reviewed':
                        try:
                            reviews_df = pd.read_csv(REVIEWS_FILE)
                            review_data = reviews_df[reviews_df['proposal_index'] == index]
                            if not review_data.empty:
                                st.success("This delivery has been reviewed.")
                                review = review_data.iloc[0]
                                st.write(f"**Rating:** {'⭐' * int(review['rating'])}")
                                st.write(f"**Feedback:** {review['review']}")
                            else:
                                st.info("Review data not found.")
                        except (FileNotFoundError, pd.errors.EmptyDataError):
                            st.info("No reviews file found.")


def procurement_dashboard():
    st.title("📊 Procurement Dashboard")
    
    proposals_df = load_and_validate_df(VENDORS_FILE, VENDOR_COLUMNS)
    cert_pending_count = len(proposals_df[proposals_df['status'].isin(['Awaiting Certificates', 'Certificates Submitted'])])

    tab1, tab2, tab3 = st.tabs(["🏆 Smart Analysis", f"📜 Certificate Verification ({cert_pending_count})", "🚚 Track Deliveries"])
    with tab1:
        with st.expander("📝 Set & Manage Project Requirements"):
            st.selectbox("Category", list(BRAND_OPTIONS.keys()) + ["Other"], key="req_cat_selector")
            with st.form("req_form", clear_on_submit=True):
                category = st.session_state.req_cat_selector
                st.subheader(f"Add New Requirement for {category}")
                item = st.text_input("Item Name")
                rate = st.number_input("Budgeted Rate", 0.01)
                quantity_unit = QUANTITY_UNITS.get(category, "")
                if not quantity_unit:
                    quantity_unit = st.text_input("Specify Unit of Measurement")
                quantity = st.number_input(f"Budgeted Quantity (in {quantity_unit or 'Units'})", 1)
                req_quality = st.selectbox("Required Quality", QUALITY_LEVELS)
                req_certs = st.multiselect("Required Certifications", MATERIAL_CERTIFICATIONS.get(category, []))
                req_date = st.date_input("Required Delivery Date")
                
                if st.form_submit_button("Save Requirement"):
                    if all([category, item, rate, quantity, quantity_unit]):
                        with open(REQUIREMENTS_FILE, "a", newline='', encoding='utf-8') as f:
                            csv.writer(f).writerow([category, item, rate, quantity, quantity_unit, req_quality, ", ".join(req_certs), req_date])
                        st.success(f"Requirement for '{item}' saved.")
            
            st.subheader("Current Requirements")
            try:
                reqs_df = load_and_validate_df(REQUIREMENTS_FILE, REQUIREMENT_COLUMNS)
                if st.session_state.edit_req_idx is not None:
                    edit_index = st.session_state.edit_req_idx
                    req_to_edit = reqs_df.iloc[edit_index]
                    with st.form("edit_req_form"):
                        st.warning(f"Editing requirement for: **{req_to_edit['item_name']}**")
                        rate = st.number_input("Budgeted Rate", value=float(req_to_edit['budgeted_rate']))
                        edit_quantity_unit = req_to_edit.get('budgeted_quantity_unit', QUANTITY_UNITS.get(req_to_edit['item_category'], "Units"))
                        quantity = st.number_input(f"Budgeted Quantity (in {edit_quantity_unit})", value=int(req_to_edit['budgeted_quantity']))
                        
                        save_col, cancel_col = st.columns(2)
                        if save_col.form_submit_button("Save Changes"):
                            reqs_df.loc[edit_index, 'budgeted_rate'] = rate
                            reqs_df.loc[edit_index, 'budgeted_quantity'] = quantity
                            reqs_df.to_csv(REQUIREMENTS_FILE, index=False)
                            st.session_state.edit_req_idx = None
                            st.success("Requirement updated!")
                            st.rerun()
                        if cancel_col.form_submit_button("Cancel"):
                            st.session_state.edit_req_idx = None
                            st.rerun()
                else:
                    if reqs_df.empty:
                        st.info("No requirements set.")
                    else:
                        for index, row in reqs_df.iterrows():
                            display_quantity_unit = row.get('budgeted_quantity_unit', QUANTITY_UNITS.get(row['item_category'], "Units"))
                            col1, col2, col3, col4, col5 = st.columns([4, 2, 2, 1, 1])
                            col1.write(f"**{row['item_name']}** ({row['item_category']})")
                            col2.write(f"Rate: ₹{row['budgeted_rate']:.2f}")
                            col3.write(f"Qty: {row['budgeted_quantity']} {display_quantity_unit}")
                            if col4.button("Edit", key=f"edit_{index}"):
                                st.session_state.edit_req_idx = index
                                st.rerun()
                            if col5.button("Delete", key=f"del_{index}"):
                                reqs_df.drop(index, inplace=True)
                                reqs_df.to_csv(REQUIREMENTS_FILE, index=False)
                                st.rerun()

            except (FileNotFoundError, pd.errors.EmptyDataError):
                st.info("No requirements set.")

        st.header("🏆 Smart Proposal Analysis")
        try:
            reqs_df = load_and_validate_df(REQUIREMENTS_FILE, REQUIREMENT_COLUMNS)
            if reqs_df.empty:
                st.info("Set a requirement to enable analysis.")
            else:
                def clear_analysis(): st.session_state.analysis_results = None
                
                category_to_analyze = st.selectbox("Analyze Category", reqs_df['item_category'].unique(), on_change=clear_analysis)
                if category_to_analyze:
                    category_reqs = reqs_df[reqs_df['item_category'] == category_to_analyze]
                    avg_rate = category_reqs['budgeted_rate'].mean()
                    
                    st.metric(f"Avg. Budget Rate for {category_to_analyze}", f"₹{avg_rate:,.2f}")
                    pending = proposals_df[(proposals_df['category'] == category_to_analyze) & (proposals_df['status'] == 'Pending')].copy()
                    
                    if st.session_state.analysis_results is None and not pending.empty:
                        st.subheader(f"All Pending Proposals for {category_to_analyze}")
                        st.dataframe(pending[['company', 'brand', 'item', 'measurement', 'quantity', 'rate', 'offered_quality']], use_container_width=True)

                    if not pending.empty:
                        site_address = st.text_input("Project Site Address", "Kochi, Kerala")
                        col1, col2, col3 = st.columns(3)
                        rate_w = col1.slider("Rate Importance", 0.0, 1.0, 0.5)
                        dist_w = col2.slider("Distance Importance", 0.0, 1.0, 0.3)
                        rating_w = col3.slider("Rating Importance", 0.0, 1.0, 0.2)

                        if st.button("Analyze"):
                            with st.spinner("Analyzing..."):
                                vendor_ratings = get_vendor_ratings()
                                pending['average_rating'] = pending['submitted_by'].map(vendor_ratings).fillna(3.0)

                                dist_text, dist_meters = zip(*[get_distance(row['address'], site_address) for _, row in pending.iterrows()])
                                pending['distance_km'] = [d / 1000 if d > 0 else np.nan for d in dist_meters]
                                pending['distance_display'] = dist_text

                                epsilon = 1e-9
                                pending['rate_score'] = abs(pending['rate'] - avg_rate) / (avg_rate + epsilon)
                                pending['dist_norm'] = (pending['distance_km'] - pending['distance_km'].min()) / (pending['distance_km'].max() - pending['distance_km'].min() + epsilon)
                                pending['rating_score'] = (5 - pending['average_rating']) / 4
                                
                                pending.fillna({'dist_norm': 0}, inplace=True)
                                pending['final_score'] = (pending['rate_score'] * rate_w) + (pending['dist_norm'] * dist_w) + (pending['rating_score'] * rating_w)
                                st.session_state.analysis_results = pending.sort_values('final_score')
                                st.session_state.analyzed_category = category_to_analyze
                                st.rerun()

                if st.session_state.analysis_results is not None:
                    results = st.session_state.analysis_results
                    st.subheader(f"🏆 Top Matches for '{category_to_analyze}'")
                    for rank, (idx, row) in enumerate(results.head(3).iterrows(), 1):
                        with st.container(border=True):
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Rank", f"#{rank}")
                            c2.metric("Rate", f"₹{row['rate']:,.2f}", delta=f"₹{row['rate'] - avg_rate:,.2f}")
                            c3.metric("Distance", row['distance_display'])
                            c4.metric("Vendor Rating", f"{row['average_rating']:.2f} ⭐")

                            st.write(f"**{row['company']}** | **{row['brand']}** | **{row['item']} ({row['measurement']}) | Score:** {row['final_score']:.2f}")
                            ac1, ac2 = st.columns(2)
                            if ac1.button("✅ Accept & Request Certificates via Email", key=f"acc_{idx}"):
                                proposals_df.loc[idx, 'status'] = "Awaiting Certificates"
                                proposals_df.to_csv(VENDORS_FILE, index=False)
                                add_notification(row['submitted_by'], f"ACTION: Your proposal for '{row['item']}' is provisionally accepted. Please email certificates to {PROCUREMENT_EMAIL}.")
                                st.success(f"Certificate request sent to {row['company']}.")
                                clear_analysis()
                                st.rerun()
                            if ac2.button("❌ Reject", key=f"rej_{idx}"):
                                proposals_df.loc[idx, 'status'] = "Rejected"
                                proposals_df.to_csv(VENDORS_FILE, index=False)
                                add_notification(row['submitted_by'], f"Your proposal for '{row['item']}' has been rejected.")
                                st.warning(f"Rejected {row['company']}'s proposal.")
                                clear_analysis()
                                st.rerun()
                    
                    if len(results) > 3:
                        st.subheader("Other Proposals")
                        st.dataframe(results.iloc[3:][['company', 'brand', 'item', 'rate', 'distance_display', 'final_score']], use_container_width=True)

        except (FileNotFoundError, pd.errors.EmptyDataError):
            st.info("No data for analysis.")

    with tab2:
        st.header("📜 Certificate Verification")
        proposals_df = load_and_validate_df(VENDORS_FILE, VENDOR_COLUMNS)
        cert_pending = proposals_df[proposals_df['status'] == 'Certificates Submitted']
        if cert_pending.empty:
            st.info("No proposals are currently awaiting final verification.")
        else:
            for index, row in cert_pending.iterrows():
                with st.container(border=True):
                    st.subheader(f"Final Verification: {row['item']} from {row['company']}")
                    st.info("This vendor has confirmed they have emailed the required certificates. Please verify them in your inbox.")
                    
                    ac1, ac2 = st.columns(2)
                    if ac1.button("✅ Final Accept", key=f"final_acc_{index}"):
                        proposals_df.loc[index, 'status'] = "Accepted"
                        proposals_df.to_csv(VENDORS_FILE, index=False)
                        add_notification(row['submitted_by'], f"Your proposal for '{row['item']}' has been ACCEPTED.")
                        add_notification("ALL_SITE", f"Approved: '{row['item']}' from {row['company']}.")
                        st.success(f"Accepted proposal from {row['company']}.")
                        st.rerun()
                    if ac2.button("❌ Final Reject", key=f"final_rej_{index}"):
                        proposals_df.loc[index, 'status'] = "Rejected"
                        proposals_df.to_csv(VENDORS_FILE, index=False)
                        add_notification(row['submitted_by'], f"Your proposal for '{row['item']}' was rejected after review.")
                        st.warning(f"Rejected proposal from {row['company']}.")
                        st.rerun()
    
    with tab3:
        st.header("🚚 Track Deliveries")
        try:
            orders = pd.read_csv(VENDORS_FILE)
            trackable = orders[orders['status'].isin(['Accepted', 'Out for Delivery', 'Delivered', 'Reviewed'])]
            if trackable.empty:
                st.info("No orders in delivery phase.")
            else:
                for _, row in trackable.iterrows():
                    with st.expander(f"**{row['item']}** from **{row['company']}** - Status: **{row['status']}**"):
                        if row['status'] == 'Out for Delivery':
                            st.success(f"Dispatched for: {row['scheduled_delivery_datetime']}")
                            st.write(f"Delivery by: **{row['delivery_boy_name']}** ({row['delivery_boy_phone']})")
                        elif row['status'] == 'Accepted':
                            st.warning("Waiting for vendor dispatch.")
                        elif row['status'] in ['Delivered', 'Reviewed']:
                            st.info("Item delivered to site.")
        except (FileNotFoundError, pd.errors.EmptyDataError):
            st.info("No orders found.")


def site_dashboard():
    st.title("📋 Site Team Dashboard")
    st.info("View items, track deliveries, and review materials.")

    df = load_and_validate_df(VENDORS_FILE, VENDOR_COLUMNS)
    site_df = df[df['status'].isin(['Accepted', 'Out for Delivery', 'Delivered', 'Reviewed'])].copy()

    if site_df.empty:
        st.warning("No items are currently in the delivery or review phase.")
        return

    # Dynamic Tab Labels
    incoming_count = len(site_df[site_df['status'] == "Out for Delivery"])
    pending_review_count = len(site_df[site_df['status'] == "Delivered"])
    
    tab1, tab2, tab3, tab4 = st.tabs([
        f"🚚 Incoming Deliveries ({incoming_count})", 
        f"⭐ Pending Review ({pending_review_count})", 
        "👍 Approved & Waiting", 
        "📖 Completed History"
    ])

    with tab1:
        incoming_df = site_df[site_df['status'] == "Out for Delivery"]
        if incoming_df.empty:
            st.info("No items are currently out for delivery.")
        else:
            for index, row in incoming_df.iterrows():
                with st.container(border=True):
                    st.subheader(f"{row['item']} ({row['brand']}) from {row['company']}")
                    st.success(f"**Scheduled Delivery:** {row['scheduled_delivery_datetime']}")
                    st.write(f"**Delivery Person:** {row['delivery_boy_name']} ({row['delivery_boy_phone']})")
                    if st.button("✅ Confirm Receipt of Item", key=f"receive_{index}"):
                        df.loc[index, 'status'] = "Delivered"
                        df.to_csv(VENDORS_FILE, index=False)
                        add_notification(row['submitted_by'], f"Delivery of '{row['item']}' was received.")
                        add_notification("ALL_PROCUREMENT", f"DELIVERED: '{row['item']}' from {row['company']}.")
                        st.success("Delivery confirmed!")
                        st.rerun()

    with tab2:
        pending_review_df = site_df[site_df['status'] == "Delivered"]
        if pending_review_df.empty:
            st.info("No items are currently pending review.")
        else:
            for index, row in pending_review_df.iterrows():
                with st.container(border=True):
                    st.subheader(f"Review: {row['item']} from {row['company']}")
                    with st.form(key=f"review_form_{index}"):
                        rating_options = ['⭐', '⭐⭐', '⭐⭐⭐', '⭐⭐⭐⭐', '⭐⭐⭐⭐⭐']
                        rating_str = st.radio("Rate material quality:", rating_options, index=4, horizontal=True)
                        rating = len(rating_str)
                        review_text = st.text_area("Review (optional)")
                        if st.form_submit_button("Submit Review"):
                            with open(REVIEWS_FILE, "a", newline='', encoding='utf-8') as f:
                                csv.writer(f).writerow([index, rating, review_text, st.session_state.username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
                            df.loc[index, 'status'] = "Reviewed"
                            df.to_csv(VENDORS_FILE, index=False)
                            add_notification("ALL_PROCUREMENT", f"REVIEW: A {rating}-star review for '{row['item']}' from {row['company']}.")
                            st.success("Review submitted!")
                            st.rerun()

    with tab3:
        approved_df = site_df[site_df['status'] == "Accepted"]
        if approved_df.empty:
            st.info("No items are currently waiting for vendor dispatch.")
        else:
            for index, row in approved_df.iterrows():
                with st.container(border=True):
                    st.subheader(f"{row['item']} ({row['brand']}) from {row['company']}")
                    st.info("This item is approved and is waiting for the vendor to dispatch.")
                    st.write(f"**Specification:** {row['measurement']}")
                    st.write(f"📞 Vendor Contact: {row['phone']}")

    with tab4:
        reviewed_df = site_df[site_df['status'] == "Reviewed"]
        if reviewed_df.empty:
            st.info("No items have been reviewed yet.")
        else:
            for index, row in reviewed_df.iterrows():
                with st.container(border=True):
                    st.subheader(f"{row['item']} ({row['brand']}) from {row['company']}")
                    st.success("✔️ Delivery completed and reviewed.")
                    try:
                        reviews_df = pd.read_csv(REVIEWS_FILE)
                        review_data = reviews_df[reviews_df['proposal_index'] == index].iloc[0]
                        st.write(f"**Your Rating:** {'⭐' * int(review_data['rating'])}")
                        st.write(f"**Your Feedback:** {review_data['review']}")
                    except (FileNotFoundError, pd.errors.EmptyDataError, IndexError):
                        st.write("Could not retrieve review details.")


# --- Main App Logic ---
def main():
    if not st.session_state.logged_in:
        page = st.session_state.get('page', 'Login', )
        if page == "Sign Up":
            signup_page()
        else:
            login_page()
    else:
        with st.sidebar:
            st.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})")
            if st.button("🚪 Logout"):
                for key in list(st.session_state.keys()):
                    if key != 'page':
                        del st.session_state[key]
                st.session_state.logged_in = False
                st.session_state.page = "Login"
                st.rerun()
            display_notifications()

        role = st.session_state.role
        if role == "Procurement":
            procurement_dashboard()
        elif role == "Site":
            site_dashboard()
        elif role == "Vendor":
            vendor_dashboard()
        else:
            st.error("Invalid role assigned.")

if __name__ == "__main__":
    main()
