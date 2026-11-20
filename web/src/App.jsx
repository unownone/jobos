import { Route, Routes } from "react-router-dom";
import { AdminSignup, Board, Data, Gate, Home, Invites, Join, Landing, Login, Memory, Onboarding, Skills, Start, Users } from "./hub.jsx";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/start" element={<Start />} />
      <Route path="/login" element={<Login />} />
      <Route path="/admin/signup" element={<AdminSignup />} />
      <Route path="/join/:id" element={<Join />} />
      <Route path="/home" element={<Gate>{(me) => <Home me={me} />}</Gate>} />
      <Route path="/board" element={<Gate>{(me) => <Board me={me} />}</Gate>} />
      <Route path="/onboarding" element={<Gate>{(me) => <Onboarding me={me} />}</Gate>} />
      <Route path="/admin" element={<Gate>{(me) => <Invites me={me} />}</Gate>} />
      <Route path="/admin/users" element={<Gate>{(me) => <Users me={me} />}</Gate>} />
      <Route path="/admin/data" element={<Gate>{(me) => <Data me={me} />}</Gate>} />
      <Route path="/admin/skills" element={<Gate>{(me) => <Skills me={me} />}</Gate>} />
      <Route path="/admin/memory" element={<Gate>{(me) => <Memory me={me} />}</Gate>} />
    </Routes>
  );
}
