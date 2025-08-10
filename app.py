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

# --- Database Connection ---
# Initialize connection.
# Uses st.connection with credentials stored in secrets.toml
conn = st.connection("mydb", type="sql")

# --- Pydeck Import (for Maps) ---
try:
    import pydeck as pdk
except ImportError:
    st.error("Please install pydeck and polyline: pip install pydeck polyline")
    pdk = None

# --- Google Maps Client Initialization ---
try:
    gmaps = googlemaps.Client(key=st.secrets["Maps_API_KEY"])
except (FileNotFoundError, KeyError):
    gmaps = None

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
def get_vendor_ratings():
    reviews_df = conn.query("SELECT * FROM reviews;")
    vendors_df = conn.query("SELECT * FROM proposals;")
    vendors_df = vendors_df.reset_index().rename(columns={'id': 'proposal_index'})
    if not reviews_df.empty and not vendors_df.empty:
        merged_df = pd.merge(reviews_df, vendors_df, on='proposal_index')
        return merged_df.groupby('submitted_by')['rating'].mean().to_dict()
    return {}

def switch_page(page_name):
    st.session_state.page = page_name
    st.rerun()

def add_notification(username, message):
    timestamp = datetime.now()
    if username in ["ALL_PROCUREMENT", "ALL_SITE"]:
        users_df = conn.query("SELECT username, role FROM users;")
        target_role = "Procurement" if username == "ALL_PROCUREMENT" else "Site"
        target_users = users_df[users_df['role'] == target_role]['username'].tolist()
        for user in target_users:
            conn.execute("INSERT INTO notifications (username, message, timestamp, is_read) VALUES (:user, :message, :timestamp, FALSE);",
                         params={"user": user, "message": message, "timestamp": timestamp})
    else:
        conn.execute("INSERT INTO notifications (username, message, timestamp, is_read) VALUES (:user, :message, :timestamp, FALSE);",
                     params={"user": username, "message": message, "timestamp": timestamp})

def get_notifications(username):
    notifications_df = conn.query("SELECT * FROM notifications WHERE username = :username AND is_read = FALSE;", params={"username": username})
    if not notifications_df.empty:
        notifications_df['timestamp'] = pd.to_datetime(notifications_df['timestamp'])
        return notifications_df.sort_values(by='timestamp', ascending=False)
    return pd.DataFrame()

def mark_notifications_as_read(username):
    conn.execute("UPDATE notifications SET is_read = TRUE WHERE username = :username;", params={"username": username})

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
                users_df = conn.query("SELECT * FROM users WHERE username = :username AND role = 'Vendor';", params={"username": new_username})
                if not users_df.empty:
                    st.error("Username already taken.")
                else:
                    conn.execute("INSERT INTO users (username, password, role) VALUES (:username, 'N/A', 'Vendor');", params={"username": new_username})
                    conn.execute("INSERT INTO vendor_profiles (vendor_username, year_of_establishment, ownership_type) VALUES (:username, :year, :ownership);",
                                 params={"username": new_username, "year": year_of_establishment, "ownership": ownership_type})
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
            user_data = conn.query("SELECT * FROM users WHERE username = :username AND role = :role;", params={"username": username, "role": role})
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
    if st.button("New Vendor? Register Here"):
        switch_page("Sign Up")

# --- Dashboards ---
def vendor_dashboard():
    st.title(f"📤 Welcome, {st.session_state.username} (Vendor Portal)")

    my_proposals = conn.query("SELECT * FROM proposals WHERE submitted_by = :username;", params={"username": st.session_state.username})
    my_proposal_indices = my_proposals.index.tolist()

    try:
        reviews_df = conn.query("SELECT * FROM reviews;")
        my_reviews = reviews_df[reviews_df['proposal_index'].isin(my_proposal_indices)]
        if not my_reviews.empty:
            average_rating = my_reviews['rating'].mean()
            st.metric(label="⭐ Your Average Rating", value=f"{average_rating:.2f} / 5")
        else:
            st.metric(label="⭐ Your Average Rating", value="No reviews yet")
    except Exception:
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
                    conn.execute("""
                        INSERT INTO proposals (submitted_by, company, category, brand, item, measurement, quantity, quantity_unit, rate, phone, address, status, offered_quality, offered_certifications)
                        VALUES (:submitted_by, :company, :category, :brand, :item, :measurement, :quantity, :quantity_unit, :rate, :phone, :address, 'Pending', :offered_quality, :offered_certifications);
                    """, params={
                        "submitted_by": st.session_state.username, "company": company, "category": category,
                        "brand": brand, "item": item, "measurement": measurement, "quantity": quantity,
                        "quantity_unit": quantity_unit, "rate": rate, "phone": phone, "address": address,
                        "offered_quality": offered_quality, "offered_certifications": ", ".join(offered_certs)
                    })
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
                        st.session_state.edit_proposal_idx = int(row['id'])
                        st.rerun()
        
        if st.session_state.edit_proposal_idx is not None:
            edit_index = st.session_state.edit_proposal_idx
            proposal_to_edit = my_proposals[my_proposals['id'] == edit_index].iloc[0]
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
                        conn.execute("""
                            UPDATE proposals SET company=:company, brand=:brand, item=:item, measurement=:measurement, 
                            quantity=:quantity, rate=:rate, phone=:phone, address=:address WHERE id=:id;
                        """, params={"company": company, "brand": brand, "item": item, "measurement": measurement, 
                                     "quantity": quantity, "rate": rate, "phone": phone, "address": address, "id": edit_index})
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
                        conn.execute("UPDATE proposals SET status = 'Certificates Submitted' WHERE id = :id;", params={"id": int(row['id'])})
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
                                conn.execute("""
                                    UPDATE proposals SET status = 'Out for Delivery', delivery_boy_name = :name, 
                                    delivery_boy_phone = :phone, scheduled_delivery_datetime = :dt WHERE id = :id;
                                """, params={"name": name, "phone": phone, "dt": dt, "id": int(row['id'])})
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
                        reviews_df = conn.query("SELECT * FROM reviews WHERE proposal_index = :index;", params={"index": int(row['id'])})
                        if not reviews_df.empty:
                            st.success("This delivery has been reviewed.")
                            review = reviews_df.iloc[0]
                            st.write(f"**Rating:** {'⭐' * int(review['rating'])}")
                            st.write(f"**Feedback:** {review['review']}")
                        else:
                            st.info("Review data not found.")


def procurement_dashboard():
    st.title("📊 Procurement Dashboard")
    
    proposals_df = conn.query("SELECT * FROM proposals;")
    cert_pending_count = len(proposals_df[proposals_df['status'].isin(['Awaiting Certificates', 'Certificates Submitted'])])

    tab1, tab2, tab3 = st.tabs(["🏆 Smart Analysis", f"📜 Certificate Verification ({cert_pending_count})", "🚚 Track Deliveries"])
    with tab1:
        with st.expander("📝 Set Project Requirements"):
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
                        conn.execute("""
                            INSERT INTO requirements (item_category, item_name, budgeted_rate, budgeted_quantity, budgeted_quantity_unit, required_quality, required_certifications, required_delivery_date)
                            VALUES (:category, :item, :rate, :quantity, :unit, :quality, :certs, :date);
                        """, params={"category": category, "item": item, "rate": rate, "quantity": quantity, "unit": quantity_unit, "quality": req_quality, "certs": ", ".join(req_certs), "date": req_date})
                        st.success(f"Requirement for '{item}' saved.")
            
            st.subheader("Current Requirements")
            reqs_df = conn.query("SELECT * FROM requirements ORDER BY id DESC;")
            if not reqs_df.empty:
                st.dataframe(reqs_df, use_container_width=True)
            else:
                st.info("No requirements set.")

        st.header("🏆 Smart Proposal Analysis")
        reqs_df = conn.query("SELECT * FROM requirements;")
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
                            conn.execute("UPDATE proposals SET status = 'Awaiting Certificates' WHERE id = :id;", params={"id": int(row['id'])})
                            add_notification(row['submitted_by'], f"ACTION: Your proposal for '{row['item']}' is provisionally accepted. Please email certificates to {PROCUREMENT_EMAIL}.")
                            st.success(f"Certificate request sent to {row['company']}.")
                            clear_analysis()
                            st.rerun()
                        if ac2.button("❌ Reject", key=f"rej_{idx}"):
                            conn.execute("UPDATE proposals SET status = 'Rejected' WHERE id = :id;", params={"id": int(row['id'])})
                            add_notification(row['submitted_by'], f"Your proposal for '{row['item']}' has been rejected.")
                            st.warning(f"Rejected {row['company']}'s proposal.")
                            clear_analysis()
                            st.rerun()
                
                if len(results) > 3:
                    st.subheader("Other Proposals")
                    st.dataframe(results.iloc[3:][['company', 'brand', 'item', 'rate', 'distance_display', 'final_score']], use_container_width=True)

    with tab2:
        st.header("📜 Certificate Verification")
        cert_pending = proposals_df[proposals_df['status'].isin(['Awaiting Certificates', 'Certificates Submitted'])]
        if cert_pending.empty:
            st.info("No proposals are currently awaiting certificate verification.")
        else:
            for index, row in cert_pending.iterrows():
                with st.container(border=True):
                    st.subheader(f"Final Verification: {row['item']} from {row['company']}")
                    if row['status'] == 'Awaiting Certificates':
                        st.warning("Waiting for vendor to confirm they have emailed certificates.")
                    else: # Certificates Submitted
                        st.info("This vendor has confirmed they have emailed the required certificates. Please verify them in your inbox.")
                        ac1, ac2 = st.columns(2)
                        if ac1.button("✅ Final Accept", key=f"final_acc_{index}"):
                            conn.execute("UPDATE proposals SET status = 'Accepted' WHERE id = :id;", params={"id": int(row['id'])})
                            add_notification(row['submitted_by'], f"Your proposal for '{row['item']}' has been ACCEPTED.")
                            add_notification("ALL_SITE", f"Approved: '{row['item']}' from {row['company']}.")
                            st.success(f"Accepted proposal from {row['company']}.")
                            st.rerun()
                        if ac2.button("❌ Final Reject", key=f"final_rej_{index}"):
                            conn.execute("UPDATE proposals SET status = 'Rejected' WHERE id = :id;", params={"id": int(row['id'])})
                            add_notification(row['submitted_by'], f"Your proposal for '{row['item']}' was rejected after review.")
                            st.warning(f"Rejected proposal from {row['company']}.")
                            st.rerun()
    
    with tab3:
        st.header("🚚 Track Deliveries")
        trackable = proposals_df[proposals_df['status'].isin(['Accepted', 'Out for Delivery', 'Delivered', 'Reviewed'])]
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


def site_dashboard():
    st.title("📋 Site Team Dashboard")
    st.info("View items, track deliveries, and review materials.")

    df = conn.query("SELECT * FROM proposals;")
    site_df = df[df['status'].isin(['Accepted', 'Out for Delivery', 'Delivered', 'Reviewed'])].copy()

    if site_df.empty:
        st.warning("No items are currently in the delivery or review phase.")
        return

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
                        conn.execute("UPDATE proposals SET status = 'Delivered' WHERE id = :id;", params={"id": int(row['id'])})
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
                            conn.execute("""
                                INSERT INTO reviews (proposal_index, rating, review, reviewed_by, timestamp)
                                VALUES (:index, :rating, :review, :user, :ts);
                            """, params={"index": int(row['id']), "rating": rating, "review": review_text, "user": st.session_state.username, "ts": datetime.now()})
                            conn.execute("UPDATE proposals SET status = 'Reviewed' WHERE id = :id;", params={"id": int(row['id'])})
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
                    reviews_df = conn.query("SELECT * FROM reviews WHERE proposal_index = :index;", params={"index": int(row['id'])})
                    if not reviews_df.empty:
                        review_data = reviews_df.iloc[0]
                        st.write(f"**Your Rating:** {'⭐' * int(review_data['rating'])}")
                        st.write(f"**Your Feedback:** {review_data['review']}")
                    else:
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
