import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaPlus, FaMinus } from 'react-icons/fa';
import Button from '../components/Button';
import '../styles/pages/_age-input.scss';

const AgeInput = () => {
  const navigate = useNavigate();
  const [age, setAge] = useState(0);

  const handleDecrease = () => {
    if (age > 0) {
      setAge(age - 1);
    }
  };

  const handleIncrease = () => {
    setAge(age + 1);
  };

  const handleInputChange = (e) => {
    const value = e.target.value;
   
    if (value === '' || /^\d+$/.test(value)) {
      const numValue = value === '' ? 0 : parseInt(value, 10);
      setAge(numValue);
    }
  };

  const handleInputBlur = (e) => {
    // Ensure age is at least 0 when input loses focus
    if (e.target.value === '' || parseInt(e.target.value, 10) < 0) {
      setAge(0);
    }
  };

  const handleNext = () => {
    // Save age to localStorage
    localStorage.setItem('age', age.toString());
    navigate('/selection');
  };

  return (
    <div className="age-input">
      <div className="age-input__container">
        <div className="age-input__content">
          <h2 className="age-input__title">Iltimos yoshingizni kirting</h2>
          
          <div className="age-input__controls">
            <button 
              className="age-input__button age-input__button--minus"
              onClick={handleDecrease}
              aria-label="Decrease age"
            >
              <FaMinus />
            </button>
            
            <input
              type="text"
              className="age-input__display"
              value={age}
              onChange={handleInputChange}
              onBlur={handleInputBlur}
              inputMode="numeric"
              pattern="[0-9]*"
              aria-label="Enter age"
            />
            
            <button 
              className="age-input__button age-input__button--plus"
              onClick={handleIncrease}
              aria-label="Increase age"
            >
              <FaPlus />
            </button>
          </div>
          
          <div className="age-input__next-wrapper">
            <Button onClick={handleNext} className="age-input__next-button">
              Keyingisi
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AgeInput;
