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
        fields = ('email', 'password', 'confirm_password', 'user_type')

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

        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password', None)
        email = validated_data.get('email')

        logger.info(f"Creating user: {email}")

        try:
            user = User.objects.create_user(**validated_data)
            logger.info(f"User created successfully: {user.email}")
            return user
        except Exception as e:
            logger.exception(f"Failed to create user: {e}")
            raise serializers.ValidationError(f"Failed to create user: {str(e)}")


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'user_type', 'is_staff')


class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['user_type'] = user.user_type
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
