import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <section>
      <h1>404</h1>
      <p>
        That page does not exist. <Link to="/">Go home</Link>.
      </p>
    </section>
  )
}
