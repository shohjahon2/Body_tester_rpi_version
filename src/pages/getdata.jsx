import { useEffect, useState } from "react";

function App() {
  const [hello, setHello] = useState("");
  const [status, setStatus] = useState("");
  const [user, setUser] = useState("");

  useEffect(() => {
    fetch("http://127.0.0.1:8000/hello")
      .then(res => res.json())
      .then(data => setHello(data.message));

    fetch("http://127.0.0.1:8000/status")
      .then(res => res.json())
      .then(data => setStatus(data.status));

    fetch("http://127.0.0.1:8000/user/5")
      .then(res => res.json())
      .then(data => setUser(JSON.stringify(data)));
  }, []);

  return (
    <div>
      <p>Hello: {hello}</p>
      <p>Status: {status}</p>
      <p>User: {user}</p>
    </div>
  );
}

export default App;