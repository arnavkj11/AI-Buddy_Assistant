import { Routes, Route, Navigate } from 'react-router-dom';
import Auth from './pages/Auth.tsx';
import Chat from './components/Chat.tsx';

function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/app" replace />} />
      <Route path="/login" element={<Auth mode="login" />} />
      <Route path="/register" element={<Auth mode="register" />} />
      <Route path="/app/*" element={<Chat />} />
    </Routes>
  );
}

export default App;
