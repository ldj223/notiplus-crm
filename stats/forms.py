from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from stats.platforms import PLATFORM_CHOICES

class CredentialForm(forms.Form):
 platform = forms.ChoiceField(label="플랫폼", choices=PLATFORM_CHOICES, widget=forms.Select(attrs={"class": "form-select", "id": "id_platform"}))
 alias = forms.CharField(label="별칭", required=True, widget=forms.TextInput(attrs={"class": "form-control"}))

 client_id = forms.CharField(label="Client id", required=False, widget=forms.TextInput(attrs={"class": "form-control", "id": "id_client_id"}))
 secret = forms.CharField(label="Secret Key", required=False, widget=forms.TextInput(attrs={"class": "form-control", "id": "id_secret"}))

 email = forms.CharField(label="이메일 주소", required=False, widget=forms.TextInput(attrs={"class": "form-control", "id": "id_email"}))
 password = forms.CharField(
     label="비밀번호", 
     required=False, 
     widget=forms.PasswordInput(attrs={
         "class": "form-control", 
         "id": "id_password",
         "placeholder": "********"
     })
 )

 def __init__(self, *args, **kwargs):
     super().__init__(*args, **kwargs)
     if self.initial and self.initial.get("password"):
         self.fields["password"].widget.attrs["placeholder"] = "********"
     if self.initial and self.initial.get("pk"):  # 이미 존재하는 객체인 경우
         self.fields["alias"].widget.attrs["readonly"] = "readonly"
         self.fields["platform"].widget.attrs["readonly"] = "readonly"
         self.fields["platform"].widget.attrs["style"] = "pointer-events: none; background-color: #e9ecef;"
     
     # 플랫폼에 따라 필드 라벨 변경
     platform = self.initial.get("platform") if self.initial else None
     if platform == "cozymamang":
         self.fields["email"].label = "아이디"

class SignUpForm(UserCreationForm):
    ACCOUNT_TYPES = (
        ('main', '메인 계정'),
        ('sub', '서브 계정'),
    )
    
    account_type = forms.ChoiceField(
        choices=ACCOUNT_TYPES,
        widget=forms.RadioSelect,
        label='계정 유형'
    )
    name = forms.CharField(max_length=100, label='이름')
    email = forms.EmailField(required=True, label='이메일')
    main_account = forms.CharField(
        max_length=150,
        required=False,
        label='메인 계정 아이디',
        help_text='서브 계정인 경우 메인 계정의 아이디를 입력해주세요.'
    )

    class Meta:
        model = User
        fields = ('username', 'name', 'email', 'password1', 'password2', 'account_type', 'main_account')

    def clean_main_account(self):
        account_type = self.cleaned_data.get('account_type')
        main_account = self.cleaned_data.get('main_account')

        if account_type == 'sub' and not main_account:
            raise forms.ValidationError('서브 계정인 경우 메인 계정 아이디를 입력해주세요.')

        if account_type == 'sub' and main_account:
            try:
                main_user = User.objects.get(username=main_account)
                if main_user.profile.account_type != 'main':
                    raise forms.ValidationError('입력한 계정이 메인 계정이 아닙니다.')
            except User.DoesNotExist:
                raise forms.ValidationError('존재하지 않는 메인 계정입니다.')

        return main_account

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        
        if commit:
            user.save()
            profile = user.profile
            profile.name = self.cleaned_data['name']
            profile.account_type = self.cleaned_data['account_type']
            
            if self.cleaned_data['account_type'] == 'sub':
                main_user = User.objects.get(username=self.cleaned_data['main_account'])
                profile.main_account = main_user
            
            profile.save()
        
        return user