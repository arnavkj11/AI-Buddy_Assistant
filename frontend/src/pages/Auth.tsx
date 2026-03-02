import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { signIn, signUp, confirmSignUp } from 'aws-amplify/auth';

interface AuthProps {
  mode: 'login' | 'register';
}

export default function Auth({ mode }: AuthProps) {
  const navigate = useNavigate();
  const [isConfirming, setIsConfirming] = useState(false);
  const [form, setForm] = useState({
    email: '',
    password: '',
    given_name: '',
    family_name: '',
    date_of_joining: '',
    code: ''
  });
  const [error, setError] = useState('');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm({...form, [e.target.name]: e.target.value });
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await signIn({ username: form.email, password: form.password });
      navigate('/app');
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await signUp({
        username: form.email,
        password: form.password,
        options: {
          userAttributes: {
            email: form.email,
            given_name: form.given_name,
            family_name: form.family_name,
            'custom:date_of_joining': form.date_of_joining
          }
        }
      });
      setIsConfirming(true);
      setError('');
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleConfirm = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await confirmSignUp({ username: form.email, confirmationCode: form.code });
      navigate('/login');
    } catch(err:any) {
      if (err.name === 'NotAuthorizedException' || err.message?.includes('Current status is CONFIRMED')) {
        navigate('/login');
      } else {
        setError(err.message);
      }
    }
  };

  if (isConfirming) {
    return (
      <div className="auth-container">
        <div className="auth-box">
          <h2>Verify Email</h2>
          {error && <p style={{color: 'var(--danger)', marginBottom:'1rem'}}>{error}</p>}
          <form onSubmit={handleConfirm}>
            <input name="code" placeholder="Confirmation Code" onChange={handleChange} required />
            <button type="submit">Verify</button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <div className="auth-box">
        <h2>{mode === 'login' ? 'Welcome Back' : 'Create Account'}</h2>
        {error && <p style={{color: 'var(--danger)', marginBottom:'1rem', textAlign:'center', fontSize:'0.9rem'}}>{error}</p>}
        <form onSubmit={mode === 'login' ? handleLogin : handleRegister}>
          {mode === 'register' && (
            <>
              <input name="given_name" placeholder="First Name" onChange={handleChange} required />
              <input name="family_name" placeholder="Last Name" onChange={handleChange} required />
              <input name="date_of_joining" type="date" placeholder="Date of Joining" onChange={handleChange} required />
            </>
          )}
          <input name="email" type="email" placeholder="Email" onChange={handleChange} required />
          <input name="password" type="password" placeholder="Password" onChange={handleChange} required />
          <button type="submit">{mode === 'login' ? 'Sign In' : 'Sign Up'}</button>
        </form>
        <p style={{marginTop: '1.5rem', textAlign: 'center', fontSize: '0.9rem'}}>
          {mode === 'login' ? (
            <>New here? <a href="#" onClick={(e) => { e.preventDefault(); navigate('/register'); }}>Create an account</a></>
          ) : (
            <>Already have an account? <a href="#" onClick={(e) => { e.preventDefault(); navigate('/login'); }}>Sign in</a></>
          )}
        </p>
      </div>
    </div>
  );
}
