from . import db
from datetime import datetime

class Users(db.Model):
    __tablename__ = "beneficiaries"  
    id = db.Column(db.Integer, primary_key=True) 
    first_name = db.Column(db.String(150), nullable=False)
    second_name = db.Column(db.String(150), nullable=False)
    national_id = db.Column(db.Integer,  unique=True, nullable=False)
    contact = db.Column(db.String(150), nullable=False)
    password = db.Column(db.String(200), nullable=False)

    email = db.Column(db.String(200), unique=True, nullable=True)
    user_type = db.Column(db.String(50), nullable=False, default='smartphone')

    current_jti = db.Column(db.String(120))  # for JWT tracking
    time_stamp = db.Column(db.DateTime, default=datetime.utcnow)

    aid_token = db.Column(db.String(100), unique=True, nullable=True) 
    token_status = db.Column(db.String(20), default='inactive')          
    token_issued_at = db.Column(db.DateTime, default=datetime.utcnow,nullable=True)
    token_expires_at = db.Column(db.DateTime, default=datetime.utcnow,nullable=True)  

    distribution_session_id= db.Column(db.Integer, db.ForeignKey('distribution_session.id'), nullable=True)  
   

    def __repr__(self):
        return f"<User {self.first_name}>"



class TokenBlocklist(db.Model):
    id=db.Column(db.Integer,primary_key=True)   
    jti=db.Column(db.String(150),unique=True,nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('beneficiaries.id'))
    created_at=db.Column(db.DateTime,default=datetime.utcnow)


    def __repr__(self):
        return f"<Token {self.jti}>"
    

class UssdSession(db.Model):
    id=db.Column(db.Integer, primary_key=True)
    session_id=db.Column(db.String(150),unique=True,nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('beneficiaries.id'))
    authenticated=db.Column(db.Boolean, default=False)
    last_active =db.Column(db.DateTime,default=datetime.utcnow)

    
    def __repr__(self):
        return f"<Session {self.session_id}>"
    



class DistributionSession(db.Model):
        __tablename__ = "distribution_session"  
        id = db.Column(db.Integer, primary_key=True)
        aid_center_name = db.Column(db.String(150), nullable=False)
        start_time = db.Column(db.DateTime, default=datetime.utcnow)
        expiry_time = db.Column(db.DateTime, nullable=True)
        is_active = db.Column(db.Boolean, default=True)

        def __repr__(self):
         return f"<Session {self.aid_center_name}>"