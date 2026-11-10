"""Authentication page controllers built on Django's standard forms and sessions."""
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.utils.http import url_has_allowed_host_and_scheme

# Register a new account, establish its authenticated session, or redisplay errors.
# Parameters: request contains registration form data on POST.
# Returns: a redirect after successful registration or the registration template.
def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')
        
    error_message = None
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
        else:
            error_message = "Registration failed. Invalid username or password patterns."
    else:
        form = UserCreationForm()
        
    return render(request, 'registration/register.html', {'form': form, 'error': error_message})

# Authenticate submitted credentials and create a Django login session on success.
# Parameters: request contains credentials on POST or renders a blank login form on GET.
# Returns: a redirect to the dashboard or the login template with validation errors.
def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
        
    error_message = None
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # Honour ?next= for same-site targets only (B-12).
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(next_url)
            return redirect('home')
        else:
            error_message = "Authentication failed. Invalid username or security credentials."
    else:
        form = AuthenticationForm()
        
    return render(request, 'registration/login.html', {'form': form, 'error': error_message})

# Terminate the current Django session and send the browser to the login page.
# Parameters: request is the active authenticated or anonymous HTTP request.
# Returns: an HTTP redirect to the login route.
def logout_view(request):
    logout(request)
    return redirect('login')