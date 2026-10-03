import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { MyBookingsPage } from './pages/MyBookingsPage';
import { RoomPage } from './pages/RoomPage';
import { RoomsPage } from './pages/RoomsPage';

export function App() {
  return (
    <div className="app">
      <header className="app__header">
        <h1>Bookings</h1>
        <nav>
          <NavLink to="/rooms">Rooms</NavLink>
          <NavLink to="/bookings">My bookings</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/rooms" element={<RoomsPage />} />
          <Route path="/rooms/:roomId" element={<RoomPage />} />
          <Route path="/bookings" element={<MyBookingsPage />} />
          <Route path="*" element={<Navigate to="/rooms" replace />} />
        </Routes>
      </main>
    </div>
  );
}
