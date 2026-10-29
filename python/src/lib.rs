//! Native part of the `churchtools-rs` Python package.
//!
//! Only transport lives here (HTTP, auth, errors, pagination); the typed API
//! and Pydantic models are generated Python in `churchtools_rs`.

#[pyo3::pymodule]
mod _core {
    use std::time::Duration;

    use churchtools_core::{Error, Method, Upload};
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::PyBytes;

    /// Converts a core error into the matching exception from `churchtools_rs._errors`.
    fn to_py_err(py: Python<'_>, err: Error) -> PyErr {
        let result = (|| -> PyResult<PyErr> {
            let errors = py.import("churchtools_rs._errors")?;
            let exc = match &err {
                Error::Api(api) => errors.call_method1(
                    "from_response",
                    (api.status, PyBytes::new(py, &api.body)),
                )?,
                Error::Decode { body, .. } => errors.call_method1(
                    "DecodeError",
                    (err.to_string(), PyBytes::new(py, body.as_bytes())),
                )?,
                Error::InvalidPath(_) => return Ok(PyValueError::new_err(err.to_string())),
                Error::Transport(_) | Error::InvalidBaseUrl(_) => {
                    errors.call_method1("TransportError", (err.to_string(),))?
                }
            };
            Ok(PyErr::from_value(exc))
        })();
        result.unwrap_or_else(|e| e)
    }

    fn parse_method(method: &str) -> PyResult<Method> {
        Method::from_bytes(method.to_ascii_uppercase().as_bytes())
            .map_err(|_| PyValueError::new_err(format!("invalid HTTP method: {method}")))
    }

    fn parse_body(body: Option<&str>) -> PyResult<Option<serde_json::Value>> {
        body.map(serde_json::from_str)
            .transpose()
            .map_err(|e| PyValueError::new_err(format!("request body is not valid JSON: {e}")))
    }

    #[pyclass(frozen, module = "churchtools_rs._core")]
    struct Client {
        inner: churchtools_core::Client,
    }

    #[pymethods]
    impl Client {
        #[new]
        #[pyo3(signature = (base_url, token=None, timeout=30.0, min_interval=None))]
        fn new(
            py: Python<'_>,
            base_url: &str,
            token: Option<String>,
            timeout: f64,
            min_interval: Option<f64>,
        ) -> PyResult<Self> {
            let mut inner =
                churchtools_core::Client::with_timeout(base_url, token, Duration::from_secs_f64(timeout))
                    .map_err(|e| to_py_err(py, e))?;
            if let Some(seconds) = min_interval {
                inner = inner.with_min_interval(Duration::from_secs_f64(seconds));
            }
            Ok(Self { inner })
        }

        /// Logs in with username and password; returns a client using that person's login token.
        fn login_with_password(&self, py: Python<'_>, username: &str, password: &str) -> PyResult<Self> {
            py.detach(|| self.inner.login_with_password(username, password))
                .map(|inner| Self { inner })
                .map_err(|e| to_py_err(py, e))
        }

        #[getter]
        fn api_url(&self) -> &str {
            self.inner.api_url()
        }

        /// Sends a request; returns the raw body or raises an `ApiError`.
        #[pyo3(signature = (method, path, query, body=None))]
        fn request<'py>(
            &self,
            py: Python<'py>,
            method: &str,
            path: &str,
            query: Vec<(String, String)>,
            body: Option<&str>,
        ) -> PyResult<Bound<'py, PyBytes>> {
            let method = parse_method(method)?;
            let body = parse_body(body)?;
            let result = py.detach(|| self.inner.request(method, path, &query, body.as_ref()));
            match result {
                Ok(bytes) => Ok(PyBytes::new(py, &bytes)),
                Err(e) => Err(to_py_err(py, e)),
            }
        }

        /// Sends a multipart upload; `files` are `(filename, content, content_type)`.
        #[allow(clippy::too_many_arguments)]
        fn request_multipart<'py>(
            &self,
            py: Python<'py>,
            method: &str,
            path: &str,
            query: Vec<(String, String)>,
            form: Vec<(String, String)>,
            file_field: &str,
            files: Vec<(String, Vec<u8>, String)>,
        ) -> PyResult<Bound<'py, PyBytes>> {
            let method = parse_method(method)?;
            let files: Vec<Upload> = files
                .into_iter()
                .map(|(name, content, content_type)| Upload::new(name, content, content_type))
                .collect();
            let result =
                py.detach(|| self.inner.request_multipart(method, path, &query, &form, file_field, &files));
            match result {
                Ok(bytes) => Ok(PyBytes::new(py, &bytes)),
                Err(e) => Err(to_py_err(py, e)),
            }
        }

        /// Iterates over the raw bodies of all pages of a paginated GET endpoint.
        fn pages(&self, path: &str, query: Vec<(String, String)>) -> Pages {
            Pages {
                inner: self.inner.pages(path, query),
            }
        }
    }

    #[pyclass(module = "churchtools_rs._core")]
    struct Pages {
        inner: churchtools_core::Pages,
    }

    #[pymethods]
    impl Pages {
        fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
            slf
        }

        fn __next__<'py>(&mut self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyBytes>>> {
            let inner = &mut self.inner;
            match py.detach(|| inner.next()) {
                None => Ok(None),
                Some(Ok(bytes)) => Ok(Some(PyBytes::new(py, &bytes))),
                Some(Err(e)) => Err(to_py_err(py, e)),
            }
        }
    }
}
