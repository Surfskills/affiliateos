import logging
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from authentication.models import User

logger = logging.getLogger('auth_api')


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('email', 'password', 'confirm_password', 'user_type', 'first_name', 'last_name')

    def validate_email(self, email):
        if User.objects.filter(email=email).exists():
            logger.error(f"Email already exists: {email}")
            raise serializers.ValidationError("A user with this email already exists.")
        if '@' not in email:
            logger.error(f"Invalid email format: {email}")
            raise serializers.ValidationError("Enter a valid email address.")
        return email

    def validate(self, attrs):
        password = attrs.get('password')
        confirm_password = attrs.get('confirm_password')

        if password != confirm_password:
            logger.error("Passwords do not match during registration.")
            raise serializers.ValidationError({'confirm_password': "Passwords do not match."})

        # Validate user_type is valid
        user_type = attrs.get('user_type')
        if user_type not in [choice[0] for choice in User.USER_TYPE_CHOICES]:
            logger.error(f"Invalid user type: {user_type}")
            raise serializers.ValidationError({'user_type': f"Invalid user type. Choose from {[choice[0] for choice in User.USER_TYPE_CHOICES]}"})

        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password', None)
        email = validated_data.get('email')
        user_type = validated_data.get('user_type')

        logger.info(f"Creating user: {email} with type: {user_type}")

        try:
            if user_type == 'admin':
                # For admin users, use create_superuser
                user = User.objects.create_superuser(**validated_data)
            elif user_type == 'support_agent':
                # For support agents, use the specialized method
                # First remove user_type as it's explicitly set in create_support_agent
                user_type_val = validated_data.pop('user_type', None)
                user = User.objects.create_support_agent(**validated_data)
            else:
                # For partners or any other type, use create_user
                user = User.objects.create_user(**validated_data)
            
            logger.info(f"User created successfully: {user.email} as {user.user_type}")
            return user
        except Exception as e:
            logger.exception(f"Failed to create user: {e}")
            raise serializers.ValidationError(f"Failed to create user: {str(e)}")


class UserSerializer(serializers.ModelSerializer):
    isAdmin = serializers.BooleanField(source='is_staff')
    user_type = serializers.CharField()

    class Meta:
        model = User
        fields = ['id', 'email', 'user_type', 'isAdmin', 'is_active']

class UserDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'user_type', 'is_staff', 'is_active', 
                  'first_name', 'last_name', 'date_joined', 'last_login')
        read_only_fields = ('id', 'email', 'date_joined', 'last_login')


class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['user_type'] = user.user_type
        token['is_support_agent'] = user.user_type == 'support_agent'
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user).data
        return data


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, min_length=8)
    token = serializers.CharField()
    uidb64 = serializers.CharField()