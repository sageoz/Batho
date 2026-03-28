import React from 'react';
import { formatDate } from './utils';

interface AppProps {
  title: string;
}

const App: React.FC<AppProps> = ({ title }) => {
  return (
    <div>
      <h1>{title}</h1>
      <p>Today is {formatDate(new Date())}</p>
    </div>
  );
};

export default App;
