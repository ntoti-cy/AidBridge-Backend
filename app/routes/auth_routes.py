from flask import Blueprint, request, jsonify
from app.models import Users
from app import db  
from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
import uuid

auth_bp = Blueprint('auth_bp', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()

    # Determine user type based on presence of email
    user_type = 'smartphone' if data.get('email') else 'ussd'

    # Required fields depending on user type
    if user_type == 'smartphone':
        required_fields = ['first_name', 'second_name','national_id', 'contact', 'email', 'password']
    else:  
        required_fields = ['first_name', 'second_name', 'national_id', 'contact', 'password']

    # Check missing fields
    missing = [field for field in required_fields if not data.get(field)]
    if missing:
        return jsonify({'error': f'Missing fields: {missing}'}), 400

    # Check if email already exists (only for smartphone users)
    if user_type == 'smartphone' and Users.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already exists'}), 409

    # Hash password for smartphone users
    hashed_password = generate_password_hash(data['password']) 

    # Create new user
    new_user = Users(
        first_name=data['first_name'],
        second_name=data['second_name'],
        national_id=data['national_id'],
        contact=data['contact'],
        email=data.get('email'),  
        password=hashed_password,
        user_type=user_type,
          current_jti=None,  # initially null
        
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        'message': f'{user_type.capitalize()} user registered successfully',
        'user_id': new_user.id,
        'user_type': new_user.user_type
    }), 201




@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    
    email = data.get('email')
    password = data.get('password')
    contact = data.get('contact')

    if not password :
        return  jsonify({'error':'Password is required'}),400
    
    #SmartPhone Login 
    if email:
        user =Users.query.filter_by(email=email, user_type='smartphone').first()
         
        if not user or not check_password_hash(user.password,password):
         return jsonify({'error':'Invalid email or password'}),401
        

    #USSD Login
    elif contact:
        user=Users.query.filter_by(contact=contact,user_type='USSD').first()

        if not user or not check_password_hash(user.password,password):
            return ({'error':'Password not Correct'}),401
        
    else:
        return jsonify({'error':'Invalid Login request'}),401
     

    #Generate session Identifier

    jti = str(uuid.uuid4())
    user.current_jti = jti
    db.session.commit()

    # Generate access token
    access_token = jwt.encode({
        'user_id': user.id,
        'jti': jti,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    }, current_app.config['SECRET_KEY'], algorithm="HS256")

    
    refresh_token = jwt.encode({
        'user_id': user.id,
        'jti': str(uuid.uuid4()),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=10)
    }, current_app.config['SECRET_KEY'], algorithm="HS256")

    return jsonify({
        'message': 'Login successful',
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user_type': user.user_type
    })
