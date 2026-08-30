const categories = [
    {
        id: 1,
        name: 'Rent',
    },
    {
        id: 2,
        name: 'Electricity',
    },
    {
        id: 3,
        name: 'Water',
    },
    {
        id: 4,
        name: 'Heating',
    },
    {
        id: 5,
        name: 'Broadband',
    }
]

export default function CategoriesPage() {
    const rows = categories.map(category => (
        <tr key={category.id}>
            <td>{category.name}</td>
            <td>£0.00</td>
            <td>£0.00</td>
        </tr>
    ))
    return (
        <table className="table-fixed w-100">
            <thead>
            <tr className="text-left">
                <th>Category</th>
                <th>Assigned</th>
                <th>Left</th>
            </tr>
            </thead>
            <tbody>
            {rows}
            </tbody>
        </table>
    );
}