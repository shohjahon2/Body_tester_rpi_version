import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import './App.scss';
import MainLayout from './layout/MainLayout';
import Registration from './pages/Registration';
import Home from './pages/Home';
import AgeInput from './pages/AgeInput';

import Selection from './pages/Selection';
import GenderSelection from './pages/GenderSelection';
import TemperatureMeasurement from './pages/TemperatureMeasurement';
import WeightHeightMeasurement from './pages/WeightHeightMeasurement';
import OxygenMeasurement from './pages/OxygenMeasurement';
import BloodPressureMeasurement from './pages/BloodPressureMeasurement';
import Success from './pages/Success';

function App() {
  return (
    <Router>
      <div className="App">
        <MainLayout>
          <Routes>
            <Route path="/" element={<Registration />} />
            <Route path="/home" element={<Home />} />
            <Route path="/age-input" element={<AgeInput />} />
        
            <Route path="/selection" element={<Selection />} />
            <Route path="/gender-selection" element={<GenderSelection />} />
            <Route path="/measurement/weight-height" element={<WeightHeightMeasurement />} />
            <Route path="/measurement/temperature" element={<TemperatureMeasurement />} />
            <Route path="/measurement/oxygen" element={<OxygenMeasurement />} />
            <Route path="/measurement/blood-pressure" element={<BloodPressureMeasurement />} />
            <Route path="/success" element={<Success />} />
          </Routes>
        </MainLayout>
      </div>
    </Router>
  );
}

export default App;
