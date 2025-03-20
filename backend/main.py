from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import pandas as pd
import random
import firebase_admin
from firebase_admin import credentials, auth
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import time
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# Initialize Firebase
cred = credentials.Certificate("firebasecredentials.json")
firebase_admin.initialize_app(cred)

# FastAPI app
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load NGO CSV data
CSV_FILE = 'ngo.csv'
df = pd.read_csv(CSV_FILE)

# OTP file storage config
OTP_FILE = 'otp_storage.json'
OTP_EXPIRY_MINUTES = 10  # OTP expires after 10 minutes

# Helper functions for OTP storage
def load_otp_store():
    """Load OTP store from file"""
    try:
        if os.path.exists(OTP_FILE):
            with open(OTP_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"Error loading OTP store: {e}")
        return {}

def save_otp_store(otp_store):
    """Save OTP store to file"""
    try:
        with open(OTP_FILE, 'w') as f:
            json.dump(otp_store, f)
        return True
    except Exception as e:
        print(f"Error saving OTP store: {e}")
        return False

def clean_expired_otps():
    """Remove expired OTPs from store"""
    otp_store = load_otp_store()
    current_time = datetime.now().timestamp()
    clean_store = {
        email: data for email, data in otp_store.items()
        if data["expires_at"] > current_time
    }
    save_otp_store(clean_store)
    return clean_store

# Models
class NGOVerification(BaseModel):
    ngo_name: str
    ngo_email: str

class OTPVerification(BaseModel):
    ngo_email: str
    otp: str

class LoginModel(BaseModel):
    email: str
    password: str

class SignupModel(BaseModel):
    ngo_email: str
    password: str

# Email sending function
def send_email(recipient, subject, body):
    sender_email = os.getenv("MAIL_USERNAME")
    sender_password = os.getenv("MAIL_PASSWORD")  # This should be an app password for Gmail
    
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = recipient
    message["Subject"] = subject
    
    message.attach(MIMEText(body, "plain"))
    
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(message)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

@app.post("/verify-ngo")
async def verify_ngo(data: NGOVerification):
    print(f"Received verification request for: {data.ngo_name}, {data.ngo_email}")
    
    # Check if NGO exists in the CSV
    matched_row = df[
        (df['Ngo Name'].str.strip().str.lower() == data.ngo_name.strip().lower()) & 
        (df['Email'].str.strip().str.lower() == data.ngo_email.strip().lower())
    ]
    
    if matched_row.empty:
        raise HTTPException(status_code=401, detail="Invalid NGO details")
    
    # Check if already registered in Firebase
    try:
        user = auth.get_user_by_email(data.ngo_email)
        raise HTTPException(status_code=400, detail="NGO already registered. Please login.")
    except auth.UserNotFoundError:
        # User not found, proceed with verification
        pass
    
    # Clean expired OTPs first
    clean_expired_otps()
    
    # Generate OTP
    otp = random.randint(100000, 999999)
    
    # Load current OTP store, add new OTP with expiry time, and save
    otp_store = load_otp_store()
    expires_at = (datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)).timestamp()
    otp_store[data.ngo_email] = {
        "otp": otp,
        "expires_at": expires_at
    }
    save_otp_store(otp_store)
    
    print(f"Generated OTP for {data.ngo_email}: {otp}")
    
    # Send OTP via email
    email_subject = "NGO Registration OTP"
    email_body = f"Your OTP for NGO registration is {otp}. This code will expire in {OTP_EXPIRY_MINUTES} minutes."
    
    if send_email(data.ngo_email, email_subject, email_body):
        return {"message": "OTP sent successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send OTP")

@app.post("/verify-otp")
async def verify_otp(data: OTPVerification):
    # Clean expired OTPs first
    otp_store = clean_expired_otps()
    
    if data.ngo_email not in otp_store:
        raise HTTPException(status_code=400, detail="No OTP request found or OTP expired")
    
    stored_otp_data = otp_store[data.ngo_email]
    
    # Check if OTP is expired
    if datetime.now().timestamp() > stored_otp_data["expires_at"]:
        # Remove expired OTP
        del otp_store[data.ngo_email]
        save_otp_store(otp_store)
        raise HTTPException(status_code=400, detail="OTP expired. Please request a new one.")
    
    # Check if OTP matches
    if stored_otp_data["otp"] != int(data.otp):
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    # Remove OTP after successful verification
    del otp_store[data.ngo_email]
    save_otp_store(otp_store)
    
    return {"message": "OTP verified successfully"}

@app.post("/complete-signup")
async def complete_signup(data: SignupModel):
    try:
        # Find NGO data from CSV
        ngo_data = df[df['Email'].str.strip().str.lower() == data.ngo_email.strip().lower()]
        
        if ngo_data.empty:
            raise HTTPException(status_code=404, detail="NGO not found in database")
            
        ngo_name = ngo_data.iloc[0]["Ngo Name"]
        
        # Create user in Firebase Authentication
        user = auth.create_user(
            email=data.ngo_email,
            password=data.password,
            display_name=ngo_name  # Store NGO name as display name
        )
        
        return {"message": "NGO registered successfully", "uid": user.uid, "ngo_name": ngo_name}
    except auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=400, detail="Email already registered")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.post("/login")
async def login(data: LoginModel):
    try:
        # Check if user exists
        try:
            user = auth.get_user_by_email(data.email)
        except auth.UserNotFoundError:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # In a real implementation, you would use Firebase Authentication REST API 
        # to validate the password as the Admin SDK doesn't provide password validation
        # For this example, we're assuming the password check happens client-side with Firebase JS SDK
        
        return {
            "message": "Login successful",
            "uid": user.uid,
            "ngo_name": user.display_name or "NGO User",
            "email": user.email
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")

# Utility endpoint to check OTP status (for debugging)
@app.get("/check-otp-status")
async def check_otp_status():
    # Only enable this in development environment
    if os.getenv("ENVIRONMENT") != "development":
        raise HTTPException(status_code=403, detail="Not allowed in production")
        
    otp_store = load_otp_store()
    # Convert timestamps to readable format for display
    readable_store = {
        email: {
            "otp": data["otp"],
            "expires_at": datetime.fromtimestamp(data["expires_at"]).strftime("%Y-%m-%d %H:%M:%S")
        } for email, data in otp_store.items()
    }
    return {"otp_count": len(otp_store), "otps": readable_store}

# For testing purposes only
@app.get("/")
async def root():
    return {"message": "NGO Verification API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
