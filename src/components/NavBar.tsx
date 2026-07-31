import {pages} from "../types.ts";

export default function NavBar({selected, onSelect}: {
    selected: typeof pages[number]['key'],
    onSelect: (page: typeof pages[number]['key']) => void
}) {
    const items = pages.map(({title, key}) => (
        <li className={key === selected ? 'text-blue-500' : undefined} key={key}
            onClick={() => onSelect(key)}>{title}</li>
    ));
    return (
        <ul className="flex flex-row gap-5">
            {items}
        </ul>
    )
}