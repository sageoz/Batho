📁 (root)/
  📄 metadata.py
    - if __name__ == "__main__":
    main() (entry_point) [L1-102]
    - analyze_repository(repo_path: Path) -> Dict[str, Any] (function) [L14-74]
    - main() -> Dict[str, Any] (function) [L77-97]
    - __name__ (entry_point) [L100-100]
    deps: pathlib, repository_metadata.json, typing

📁 src/flask/
  📄 __init__.py
    - __getattr__(name) (function) [L44-102]
    deps: markupsafe, warnings
  📄 app.py
    - _make_timedelta(value: timedelta | int | None) -> timedelta | None (function) [L85-89]
    - Flask (class) [L92-2213]
    - __init__(
        self,
        import_name: str,
        static_url_path: str | None = None,
        static_folder: str | os.PathLike | None = "static",
        static_host: str | None = None,
        host_matching: bool = False,
        subdomain_matching: bool = False,
        template_folder: str | os.PathLike | None = "templates",
        instance_path: str | None = None,
        instance_relative_config: bool = False,
        root_path: str | None = None,
    ) -> Environment (method) [L354-507]
    - _check_setup_finished(self, f_name: str) -> None (method) [L509-519]
    - make_config(self, instance_relative: bool = False) -> Config (method) [L594-608]
    - make_aborter(self) -> Aborter (method) [L610-620]
    - auto_find_instance_path(self) -> str (method) [L622-633]
    - open_instance_resource(self, resource: str, mode: str = "rb") -> t.IO[t.AnyStr] (method) [L635-645]
    - create_jinja_environment(self) -> Environment (method) [L647-685]
    - create_global_jinja_loader(self) -> DispatchingJinjaLoader (method) [L687-698]
    - select_jinja_autoescape(self, filename: str) -> bool (method) [L700-711]
    - update_template_context(self, context: dict) -> None (method) [L713-739]
    - make_shell_context(self) -> dict (method) [L741-751]
    - run(
        self,
        host: str | None = None,
        port: int | None = None,
        debug: bool | None = None,
        load_dotenv: bool = True,
        **options: t.Any,
    ) -> None (method) [L773-894]
    - test_client(self, use_cookies: bool = True, **kwargs: t.Any) -> FlaskClient (method) [L896-952]
    - test_cli_runner(self, **kwargs: t.Any) -> FlaskCliRunner (method) [L954-969]
    - iter_blueprints(self) -> t.ValuesView[Blueprint] (method) [L999-1004]
    - decorator(f: T_template_filter) -> T_template_filter (function) [L1081-1083]
    - decorator(f: T_template_test) -> T_template_test (function) [L1122-1124]
    - decorator(f: T_template_global) -> T_template_global (function) [L1160-1162]
    - _find_error_handler(self, e: Exception) -> ft.ErrorHandlerCallable | None (method) [L1225-1246]
    - handle_http_exception(
        self, e: HTTPException
    ) -> HTTPException | ft.ResponseReturnValue (method) [L1248-1281]
    - trap_http_exception(self, e: Exception) -> bool (method) [L1283-1316]
    - handle_user_exception(
        self, e: Exception
    ) -> HTTPException | ft.ResponseReturnValue (method) [L1318-1348]
    - handle_exception(self, e: Exception) -> Response (method) [L1350-1401]
    - log_exception(
        self,
        exc_info: (tuple[type, BaseException, TracebackType] | tuple[None, None, None]),
    ) -> None (method) [L1403-1416]
    - raise_routing_exception(self, request: Request) -> t.NoReturn (method) [L1418-1444]
    - dispatch_request(self) -> ft.ResponseReturnValue (method) [L1446-1469]
    - full_dispatch_request(self) -> Response (method) [L1471-1487]
    - finalize_request(
        self,
        rv: ft.ResponseReturnValue | HTTPException,
        from_error_handler: bool = False,
    ) -> Response (method) [L1489-1518]
    - make_default_options_response(self) -> Response (method) [L1520-1531]
    - should_ignore_error(self, error: BaseException | None) -> bool (method) [L1533-1541]
    - ensure_sync(self, func: t.Callable) -> t.Callable (method) [L1543-1555]
    - async_to_sync(
        self, func: t.Callable[..., t.Coroutine]
    ) -> t.Callable[..., t.Any] (method) [L1557-1578]
    - url_for(
        self,
        endpoint: str,
        *,
        _anchor: str | None = None,
        _method: str | None = None,
        _scheme: str | None = None,
        _external: bool | None = None,
        **values: t.Any,
    ) -> str (method) [L1580-1703]
    - redirect(self, location: str, code: int = 302) -> BaseResponse (method) [L1705-1717]
    - make_response(self, rv: ft.ResponseReturnValue) -> Response (method) [L1719-1857]
    - create_url_adapter(self, request: Request | None) -> MapAdapter | None (method) [L1859-1897]
    - inject_url_defaults(self, endpoint: str, values: dict) -> None (method) [L1899-1918]
    - handle_url_build_error(
        self, error: BuildError, endpoint: str, values: dict[str, t.Any]
    ) -> str (method) [L1920-1952]
    - preprocess_request(self) -> ft.ResponseReturnValue | None (method) [L1954-1979]
    - process_response(self, response: Response) -> Response (method) [L1981-2007]
    - do_teardown_request(
        self, exc: BaseException | None = _sentinel  # type: ignore
    ) -> None (method) [L2009-2040]
    - do_teardown_appcontext(
        self, exc: BaseException | None = _sentinel  # type: ignore
    ) -> None (method) [L2042-2065]
    - app_context(self) -> AppContext (method) [L2067-2086]
    - request_context(self, environ: dict) -> RequestContext (method) [L2088-2102]
    - test_request_context(self, *args: t.Any, **kwargs: t.Any) -> RequestContext (method) [L2104-2158]
    - wsgi_app(self, environ: dict, start_response: t.Callable) -> t.Any (method) [L2160-2206]
    - __call__(self, environ: dict, start_response: t.Callable) -> t.Any (method) [L2208-2213]
    deps: asgiref.sync, warnings, werkzeug.serving
  📄 blueprints.py
    - BlueprintSetupState (class) [L34-116]
    - __init__(
        self,
        blueprint: Blueprint,
        app: Flask,
        options: t.Any,
        first_registration: bool,
    ) -> None (method) [L41-85]
    - add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: t.Callable | None = None,
        **options: t.Any,
    ) -> None (method) [L87-116]
    - Blueprint (class) [L119-626]
    - __init__(
        self,
        name: str,
        import_name: str,
        static_folder: str | os.PathLike | None = None,
        static_url_path: str | None = None,
        template_folder: str | os.PathLike | None = None,
        url_prefix: str | None = None,
        subdomain: str | None = None,
        url_defaults: dict | None = None,
        root_path: str | None = None,
        cli_group: str | None = _sentinel,  # type: ignore
    ) -> None (method) [L174-211]
    - _check_setup_finished(self, f_name: str) -> None (method) [L213-221]
    - wrapper(state: BlueprintSetupState) -> None (function) [L240-242]
    - make_setup_state(
        self, app: Flask, options: dict, first_registration: bool = False
    ) -> BlueprintSetupState (method) [L246-253]
    - register(self, app: Flask, options: dict) -> None (method) [L273-407]
    - decorator(f: T_template_filter) -> T_template_filter (function) [L451-453]
    - register_template(state: BlueprintSetupState) -> None (function) [L469-470]
    - decorator(f: T_template_test) -> T_template_test (function) [L487-489]
    - register_template(state: BlueprintSetupState) -> None (function) [L507-508]
    - decorator(f: T_template_global) -> T_template_global (function) [L525-527]
    - register_template(state: BlueprintSetupState) -> None (function) [L545-546]
    - decorator(f: T_error_handler) -> T_error_handler (function) [L600-602]
  📄 cli.py
    - if __name__ == "__main__":
    main() (entry_point) [L1-1069]
    - NoAppException (class) [L29-30]
    - find_best_app(module) -> str | None (function) [L33-83]
    - _called_with_wrong_args(f) -> str | None (function) [L86-109]
    - find_app_by_string(module, app_name) -> str | None (function) [L112-185]
    - prepare_import(path) -> str | None (function) [L188-214]
    - locate_app(module_name, app_name, raise_if_not_found=True) -> str | None (function) [L217-238]
    - get_version(ctx, param, value) -> str | None (function) [L241-254]
    - ScriptInfo (class) [L267-332]
    - __init__(
        self,
        app_import_path: str | None = None,
        create_app: t.Callable[..., Flask] | None = None,
        set_debug_flag: bool = True,
    ) -> None (method) [L276-291]
    - load_app(self) -> Flask (method) [L293-332]
    - with_appcontext(f) -> str | None (function) [L338-360]
    - AppGroup (class) [L363-391]
    - command(self, *args, **kwargs) -> None (method) [L371-383]
    - decorator(f) -> str | None (function) [L378-381]
    - group(self, *args, **kwargs) -> None (method) [L385-391]
    - _set_app(ctx: click.Context, param: click.Option, value: str | None) -> str | None (function) [L394-400]
    - _set_debug(ctx: click.Context, param: click.Option, value: bool) -> bool | None (function) [L422-436]
    - _env_file_callback(
    ctx: click.Context, param: click.Option, value: str | None
) -> str | None (function) [L447-467]
    - FlaskGroup (class) [L482-645]
    - __init__(
        self,
        add_default_commands: bool = True,
        create_app: t.Callable[..., Flask] | None = None,
        add_version_option: bool = True,
        load_dotenv: bool = True,
        set_debug_flag: bool = True,
        **extra: t.Any,
    ) -> None (method) [L511-546]
    - _load_plugin_commands(self) -> None (method) [L548-563]
    - get_command(self, ctx, name) -> None (method) [L565-590]
    - list_commands(self, ctx) -> None (method) [L592-611]
    - make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: t.Any,
    ) -> click.Context (method) [L613-635]
    - parse_args(self, ctx: click.Context, args: list[str]) -> list[str] (method) [L637-645]
    - _path_is_ancestor(path, other) -> str | None (function) [L648-652]
    - load_dotenv(path: str | os.PathLike | None = None) -> bool (function) [L655-713]
    - show_server_banner(debug, app_import_path) -> str | None (function) [L716-727]
    - CertParamType (class) [L730-773]
    - __init__(self) -> None (method) [L738-739]
    - convert(self, value, param, ctx) -> None (method) [L741-773]
    - _validate_key(ctx, param, value) -> str | None (function) [L776-810]
    - SeparatedPathType (class) [L813-822]
    - convert(self, value, param, ctx) -> None (method) [L819-822]
    - main() -> None (function) [L1063-1064]
    - __name__ (entry_point) [L1067-1067]
    deps: .readthedocs.yaml, ast, click, click.core, code, cryptography, functools, importlib, importlib.metadata, inspect, operator, platform, pyproject.toml, re, readline, rlcompleter, ssl, sys, traceback, werkzeug, werkzeug.serving, werkzeug.utils
  📄 config.py
    - ConfigAttribute (class) [L12-28]
    - __init__(self, name: str, get_converter: t.Callable | None = None) -> None (method) [L15-17]
    - __get__(self, obj: t.Any, owner: t.Any = None) -> t.Any (method) [L19-25]
    - __set__(self, obj: t.Any, value: t.Any) -> None (method) [L27-28]
    - Config (class) [L31-347]
    - __init__(
        self, root_path: str | os.PathLike, defaults: dict | None = None
    ) -> None (method) [L75-79]
    - from_envvar(self, variable_name: str, silent: bool = False) -> bool (method) [L81-103]
    - from_prefixed_env(
        self, prefix: str = "FLASK", *, loads: t.Callable[[str], t.Any] = json.loads
    ) -> bool (method) [L105-167]
    - from_pyfile(self, filename: str | os.PathLike, silent: bool = False) -> bool (method) [L169-196]
    - from_object(self, obj: object | str) -> None (method) [L198-234]
    - from_file(
        self,
        filename: str | os.PathLike,
        load: t.Callable[[t.IO[t.Any]], t.Mapping],
        silent: bool = False,
        text: bool = True,
    ) -> bool (method) [L236-282]
    - from_mapping(
        self, mapping: t.Mapping[str, t.Any] | None = None, **kwargs: t.Any
    ) -> bool (method) [L284-301]
    - get_namespace(
        self, namespace: str, lowercase: bool = True, trim_namespace: bool = True
    ) -> dict[str, t.Any] (method) [L303-344]
    - __repr__(self) -> str (method) [L346-347]
  📄 ctx.py
    - _AppCtxGlobals (class) [L27-112]
    - __getattr__(self, name: str) -> t.Any (method) [L50-54]
    - __setattr__(self, name: str, value: t.Any) -> None (method) [L56-57]
    - __delattr__(self, name: str) -> None (method) [L59-63]
    - get(self, name: str, default: t.Any | None = None) -> t.Any (method) [L65-74]
    - pop(self, name: str, default: t.Any = _sentinel) -> t.Any (method) [L76-88]
    - setdefault(self, name: str, default: t.Any = None) -> t.Any (method) [L90-100]
    - __contains__(self, item: str) -> bool (method) [L102-103]
    - __iter__(self) -> t.Iterator[str] (method) [L105-106]
    - __repr__(self) -> str (method) [L108-112]
    - after_this_request(f: ft.AfterRequestCallable) -> ft.AfterRequestCallable (function) [L115-145]
    - copy_current_request_context(f: t.Callable) -> t.Callable (function) [L148-186]
    - wrapper(*args, **kwargs) -> ft.AfterRequestCallable (function) [L182-184]
    - has_request_context() -> bool (function) [L189-218]
    - has_app_context() -> bool (function) [L221-228]
    - AppContext (class) [L231-277]
    - __init__(self, app: Flask) -> None (method) [L238-242]
    - push(self) -> None (method) [L244-247]
    - pop(self, exc: BaseException | None = _sentinel) -> None (method) [L249-265]
    - __enter__(self) -> AppContext (method) [L267-269]
    - __exit__(
        self,
        exc_type: type | None,
        exc_value: BaseException | None,
        tb: TracebackType | None,
    ) -> None (method) [L271-277]
    - RequestContext (class) [L280-440]
    - __init__(
        self,
        app: Flask,
        environ: dict,
        request: Request | None = None,
        session: SessionMixin | None = None,
    ) -> None (method) [L302-326]
    - copy(self) -> RequestContext (method) [L328-346]
    - match_request(self) -> None (method) [L348-356]
    - push(self) -> None (method) [L358-385]
    - pop(self, exc: BaseException | None = _sentinel) -> None (method) [L387-422]
    - __enter__(self) -> RequestContext (method) [L424-426]
    - __exit__(
        self,
        exc_type: type | None,
        exc_value: BaseException | None,
        tb: TracebackType | None,
    ) -> None (method) [L428-434]
    - __repr__(self) -> str (method) [L436-440]
  📄 debughelpers.py
    - UnexpectedUnicodeError (class) [L10-13]
    - DebugFilesKeyError (class) [L16-40]
    - __init__(self, request, key) (method) [L21-37]
    - __str__(self) (method) [L39-40]
    - FormDataRoutingRedirect (class) [L43-70]
    - __init__(self, request) (method) [L50-70]
    - attach_enctype_error_multidict(request) -> t.Generator (function) [L73-96]
    - newcls (class) [L82-92]
    - __getitem__(self, key) (method) [L83-92]
    - _dump_loader_info(loader) -> t.Generator (function) [L99-113]
    - explain_template_loading_attempts(app: Flask, template, attempts) -> None (function) [L116-160]
  📄 globals.py
    - _FakeStack (class) [L17-33]
    - __init__(self, name: str, cv: ContextVar[t.Any]) -> None (method) [L18-20]
    - __getattr__(name: str) -> t.Any (function) [L75-96]
    deps: warnings
  📄 helpers.py
    - get_debug_flag() -> bool (function) [L30-35]
    - get_load_dotenv(default: bool = True) -> bool (function) [L38-50]
    - stream_with_context(
    generator_or_function: (
        t.Iterator[t.AnyStr] | t.Callable[..., t.Iterator[t.AnyStr]]
    )
) -> t.Iterator[t.AnyStr] (function) [L53-129]
    - generator() -> t.Generator (function) [L101-121]
    - make_response(*args: t.Any) -> Response (function) [L132-178]
    - url_for(
    endpoint: str,
    *,
    _anchor: str | None = None,
    _method: str | None = None,
    _scheme: str | None = None,
    _external: bool | None = None,
    **values: t.Any,
) -> str (function) [L181-232]
    - redirect(
    location: str, code: int = 302, Response: type[BaseResponse] | None = None
) -> BaseResponse (function) [L235-256]
    - abort(code: int | BaseResponse, *args: t.Any, **kwargs: t.Any) -> t.NoReturn (function) [L259-279]
    - get_template_attribute(template_name: str, attribute: str) -> t.Any (function) [L282-301]
    - flash(message: str, category: str = "message") -> None (function) [L304-335]
    - get_flashed_messages(
    with_categories: bool = False, category_filter: t.Iterable[str] = ()
) -> list[str] | list[tuple[str, str]] (function) [L338-377]
    - _prepare_send_file_kwargs(**kwargs: t.Any) -> dict[str, t.Any] (function) [L380-390]
    - send_file(
    path_or_file: os.PathLike | str | t.BinaryIO,
    mimetype: str | None = None,
    as_attachment: bool = False,
    download_name: str | None = None,
    conditional: bool = True,
    etag: bool | str = True,
    last_modified: datetime | int | float | None = None,
    max_age: None | (int | t.Callable[[str | None], int | None]) = None,
) -> Response (function) [L393-516]
    - send_from_directory(
    directory: os.PathLike | str,
    path: os.PathLike | str,
    **kwargs: t.Any,
) -> Response (function) [L519-559]
    - get_root_path(import_name: str) -> str (function) [L562-616]
    - locked_cached_property (class) [L619-662]
    - __init__(
        self,
        fget: t.Callable[[t.Any], t.Any],
        name: str | None = None,
        doc: str | None = None,
    ) -> None (method) [L632-647]
    - __get__(self, obj: object, type: type = None) -> t.Any (method) [L649-654]
    - __set__(self, obj: object, value: t.Any) -> None (method) [L656-658]
    - __delete__(self, obj: object) -> None (method) [L660-662]
    - is_ip(value: str) -> bool (function) [L665-691]
    deps: warnings
  📄 logging.py
    - has_level_handler(logger: logging.Logger) -> bool (function) [L28-44]
    - create_logger(app: Flask) -> logging.Logger (function) [L55-76]
  📄 scaffold.py
    - setupmethod(f: F) -> F (function) [L45-52]
    - wrapper_func(self, *args: t.Any, **kwargs: t.Any) -> t.Any (function) [L48-50]
    - Scaffold (class) [L55-771]
    - __init__(
        self,
        import_name: str,
        static_folder: str | os.PathLike | None = None,
        static_url_path: str | None = None,
        template_folder: str | os.PathLike | None = None,
        root_path: str | None = None,
    ) -> str (method) [L77-223]
    - __repr__(self) -> str (method) [L225-226]
    - _check_setup_finished(self, f_name: str) -> None (method) [L228-229]
    - get_send_file_max_age(self, filename: str | None) -> int | None (method) [L279-301]
    - send_static_file(self, filename: str) -> Response (method) [L303-319]
    - open_resource(self, resource: str, mode: str = "rb") -> t.IO[t.AnyStr] (method) [L334-355]
    - _method_route(
        self,
        method: str,
        rule: str,
        options: dict,
    ) -> t.Callable[[T_route], T_route] (method) [L357-366]
    - decorator(f: T_route) -> T_route (function) [L433-436]
    - decorator(f: F) -> F (function) [L526-528]
    - decorator(f: T_error_handler) -> T_error_handler (function) [L708-710]
    - _endpoint_from_view_func(view_func: t.Callable) -> str (function) [L774-779]
    - _path_is_relative_to(path: pathlib.PurePath, base: str) -> bool (function) [L782-788]
    - _find_package_path(import_name) -> F (function) [L791-832]
    - find_package(import_name: str) -> F (function) [L835-873]
  📄 sessions.py
    - SessionMixin (class) [L20-45]
    - SecureCookieSession (class) [L48-87]
    - __init__(self, initial: t.Any = None) -> None (method) [L70-75]
    - on_update(self) -> None (function) [L71-73]
    - __getitem__(self, key: str) -> t.Any (method) [L77-79]
    - get(self, key: str, default: t.Any = None) -> t.Any (method) [L81-83]
    - setdefault(self, key: str, default: t.Any = None) -> t.Any (method) [L85-87]
    - NullSession (class) [L90-104]
    - _fail(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn (method) [L96-101]
    - SessionInterface (class) [L107-270]
    - make_null_session(self, app: Flask) -> NullSession (method) [L157-167]
    - is_null_session(self, obj: object) -> bool (method) [L169-176]
    - get_cookie_name(self, app: Flask) -> str (method) [L178-180]
    - get_cookie_domain(self, app: Flask) -> str | None (method) [L182-193]
    - get_cookie_path(self, app: Flask) -> str (method) [L195-201]
    - get_cookie_httponly(self, app: Flask) -> bool (method) [L203-208]
    - get_cookie_secure(self, app: Flask) -> bool (method) [L210-214]
    - get_cookie_samesite(self, app: Flask) -> str (method) [L216-221]
    - get_expiration_time(self, app: Flask, session: SessionMixin) -> datetime | None (method) [L223-231]
    - should_set_cookie(self, app: Flask, session: SessionMixin) -> bool (method) [L233-247]
    - open_session(self, app: Flask, request: Request) -> SessionMixin | None (method) [L249-261]
    - save_session(
        self, app: Flask, session: SessionMixin, response: Response
    ) -> None (method) [L263-270]
    - SecureCookieSessionInterface (class) [L276-367]
    - get_signing_serializer(self, app: Flask) -> URLSafeTimedSerializer | None (method) [L295-306]
    - open_session(self, app: Flask, request: Request) -> SecureCookieSession | None (method) [L308-320]
    - save_session(
        self, app: Flask, session: SessionMixin, response: Response
    ) -> None (method) [L322-367]
  📄 signals.py
    - __getattr__(name: str) -> t.Any (function) [L23-33]
  📄 templating.py
    - _default_template_ctx_processor() -> dict[str, t.Any] (function) [L23-35]
    - Environment (class) [L38-48]
    - __init__(self, app: Flask, **options: t.Any) -> None (method) [L44-48]
    - DispatchingJinjaLoader (class) [L51-124]
    - __init__(self, app: Flask) -> None (method) [L56-57]
    - get_source(  # type: ignore
        self, environment: Environment, template: str
    ) -> tuple[str, str | None, t.Callable | None] (method) [L59-64]
    - _get_source_explained(
        self, environment: Environment, template: str
    ) -> tuple[str, str | None, t.Callable | None] (method) [L66-88]
    - _get_source_fast(
        self, environment: Environment, template: str
    ) -> tuple[str, str | None, t.Callable | None] (method) [L90-98]
    - _iter_loaders(
        self, template: str
    ) -> t.Generator[tuple[Scaffold, BaseLoader], None, None] (method) [L100-110]
    - list_templates(self) -> list[str] (method) [L112-124]
    - _render(app: Flask, template: Template, context: dict[str, t.Any]) -> str (function) [L127-136]
    - render_template(
    template_name_or_list: str | Template | list[str | Template],
    **context: t.Any,
) -> str (function) [L139-151]
    - render_template_string(source: str, **context: t.Any) -> str (function) [L154-163]
    - _stream(
    app: Flask, template: Template, context: dict[str, t.Any]
) -> t.Iterator[str] (function) [L166-186]
    - generate() -> t.Iterator[str] (function) [L174-178]
    - stream_template(
    template_name_or_list: str | Template | list[str | Template],
    **context: t.Any,
) -> t.Iterator[str] (function) [L189-205]
    - stream_template_string(source: str, **context: t.Any) -> t.Iterator[str] (function) [L208-220]
  📄 testing.py
    - EnvironBuilder (class) [L25-93]
    - __init__(
        self,
        app: Flask,
        path: str = "/",
        base_url: str | None = None,
        subdomain: str | None = None,
        url_scheme: str | None = None,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> None (method) [L47-85]
    - json_dumps(self, obj: t.Any, **kwargs: t.Any) -> str (method) [L87-93]
    - _get_werkzeug_version() -> str (function) [L99-105]
    - FlaskClient (class) [L108-259]
    - __init__(self, *args: t.Any, **kwargs: t.Any) -> None (method) [L124-132]
    - _copy_environ(self, other) -> TestResponse (method) [L184-190]
    - _request_from_builder_args(self, args, kwargs) -> TestResponse (method) [L192-199]
    - open(
        self,
        *args: t.Any,
        buffered: bool = False,
        follow_redirects: bool = False,
        **kwargs: t.Any,
    ) -> TestResponse (method) [L201-244]
    - __enter__(self) -> FlaskClient (method) [L246-250]
    - __exit__(
        self,
        exc_type: type | None,
        exc_value: BaseException | None,
        tb: TracebackType | None,
    ) -> None (method) [L252-259]
    - FlaskCliRunner (class) [L262-295]
    - __init__(self, app: Flask, **kwargs: t.Any) -> None (method) [L268-270]
    - invoke(  # type: ignore
        self, cli: t.Any = None, args: t.Any = None, **kwargs: t.Any
    ) -> t.Any (method) [L272-295]
  📄 views.py
    - View (class) [L15-134]
    - dispatch_request(self) -> ft.ResponseReturnValue (method) [L77-82]
    - MethodView (class) [L137-190]
    - __init_subclass__(cls, **kwargs: t.Any) -> None (method) [L164-179]
    - dispatch_request(self, **kwargs: t.Any) -> ft.ResponseReturnValue (method) [L181-190]
  📄 wrappers.py
    - Request (class) [L17-135]
    - _load_form_data(self) -> None (method) [L113-126]
    - on_json_loading_failed(self, e: ValueError | None) -> t.Any (method) [L128-135]
    - Response (class) [L138-173]

📁 src/flask/json/
  📄 __init__.py
    - dumps(obj: t.Any, **kwargs: t.Any) -> str (function) [L13-44]
    - dump(obj: t.Any, fp: t.IO[str], **kwargs: t.Any) -> None (function) [L47-74]
    - loads(s: str | bytes, **kwargs: t.Any) -> t.Any (function) [L77-105]
    - load(fp: t.IO[t.AnyStr], **kwargs: t.Any) -> t.Any (function) [L108-135]
    - jsonify(*args: t.Any, **kwargs: t.Any) -> Response (function) [L138-170]
  📄 provider.py
    - JSONProvider (class) [L18-104]
    - __init__(self, app: Flask) -> None (method) [L37-38]
    - dumps(self, obj: t.Any, **kwargs: t.Any) -> str (method) [L40-46]
    - dump(self, obj: t.Any, fp: t.IO[str], **kwargs: t.Any) -> None (method) [L48-56]
    - loads(self, s: str | bytes, **kwargs: t.Any) -> t.Any (method) [L58-64]
    - load(self, fp: t.IO[t.AnyStr], **kwargs: t.Any) -> t.Any (method) [L66-72]
    - _prepare_response_obj(
        self, args: tuple[t.Any, ...], kwargs: dict[str, t.Any]
    ) -> t.Any (method) [L74-86]
    - response(self, *args: t.Any, **kwargs: t.Any) -> Response (method) [L88-104]
    - _default(o: t.Any) -> t.Any (function) [L107-120]
    - DefaultJSONProvider (class) [L123-216]
    - dumps(self, obj: t.Any, **kwargs: t.Any) -> str (method) [L167-180]
    - loads(self, s: str | bytes, **kwargs: t.Any) -> t.Any (method) [L182-188]
    - response(self, *args: t.Any, **kwargs: t.Any) -> Response (method) [L190-216]
  📄 tag.py
    - JSONTag (class) [L59-89]
    - __init__(self, serializer: TaggedJSONSerializer) -> None (method) [L68-70]
    - check(self, value: t.Any) -> bool (method) [L72-74]
    - to_json(self, value: t.Any) -> t.Any (method) [L76-79]
    - to_python(self, value: t.Any) -> t.Any (method) [L81-84]
    - tag(self, value: t.Any) -> t.Any (method) [L86-89]
    - TagDict (class) [L92-115]
    - check(self, value: t.Any) -> bool (method) [L102-107]
    - to_json(self, value: t.Any) -> t.Any (method) [L109-111]
    - to_python(self, value: t.Any) -> t.Any (method) [L113-115]
    - PassDict (class) [L118-129]
    - check(self, value: t.Any) -> bool (method) [L121-122]
    - to_json(self, value: t.Any) -> t.Any (method) [L124-127]
    - TagTuple (class) [L132-143]
    - check(self, value: t.Any) -> bool (method) [L136-137]
    - to_json(self, value: t.Any) -> t.Any (method) [L139-140]
    - to_python(self, value: t.Any) -> t.Any (method) [L142-143]
    - PassList (class) [L146-155]
    - check(self, value: t.Any) -> bool (method) [L149-150]
    - to_json(self, value: t.Any) -> t.Any (method) [L152-153]
    - TagBytes (class) [L158-169]
    - check(self, value: t.Any) -> bool (method) [L162-163]
    - to_json(self, value: t.Any) -> t.Any (method) [L165-166]
    - to_python(self, value: t.Any) -> t.Any (method) [L168-169]
    - TagMarkup (class) [L172-187]
    - check(self, value: t.Any) -> bool (method) [L180-181]
    - to_json(self, value: t.Any) -> t.Any (method) [L183-184]
    - to_python(self, value: t.Any) -> t.Any (method) [L186-187]
    - TagUUID (class) [L190-201]
    - check(self, value: t.Any) -> bool (method) [L194-195]
    - to_json(self, value: t.Any) -> t.Any (method) [L197-198]
    - to_python(self, value: t.Any) -> t.Any (method) [L200-201]
    - TagDateTime (class) [L204-215]
    - check(self, value: t.Any) -> bool (method) [L208-209]
    - to_json(self, value: t.Any) -> t.Any (method) [L211-212]
    - to_python(self, value: t.Any) -> t.Any (method) [L214-215]
    - TaggedJSONSerializer (class) [L218-314]
    - __init__(self) -> None (method) [L248-253]
    - register(
        self,
        tag_class: type[JSONTag],
        force: bool = False,
        index: int | None = None,
    ) -> None (method) [L255-286]
    - tag(self, value: t.Any) -> dict[str, t.Any] (method) [L288-294]
    - untag(self, value: dict[str, t.Any]) -> t.Any (method) [L296-306]
    - dumps(self, value: t.Any) -> str (method) [L308-310]
    - loads(self, value: str) -> t.Any (method) [L312-314]
