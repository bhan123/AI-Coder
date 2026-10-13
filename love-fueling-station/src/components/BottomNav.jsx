import { Icon } from './Icons.jsx';

const items = [
  { id: 'home', label: '首页', icon: 'home' },
  { id: 'ledger', label: '账本', icon: 'book' },
  { id: 'us', label: '我们', icon: 'users' },
];

export function BottomNav({ current, onNavigate }) {
  return (
    <nav className="bottom-nav" aria-label="主要导航">
      {items.map((item) => (
        <button
          aria-current={current === item.id ? 'page' : undefined}
          className={`nav-item ${current === item.id ? 'is-active' : ''}`}
          key={item.id}
          onClick={() => onNavigate(item.id)}
          type="button"
        >
          <Icon name={item.icon} size={21} />
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
  );
}
